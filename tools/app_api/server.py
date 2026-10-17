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
import re
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
import db as DBM                                              # noqa: E402
import legal as LEGAL                                         # noqa: E402
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
MAX_ACCOUNTS = 1                 # умолчание без файла пределов: один аккаунт (оператор)
# Предел аккаунтов меняет оператор без перезапуска (спека 16 L3, 14.10):
# `out/limits.json` {"max_accounts": N}. Открыть регистрацию — решение
# владельца; число держит ёмкость машины (исполнитель на подписку).
EQUITY_TTL = 60.0
# Чтение — 600 в минуту: вкладка Trades спрашивает позиции раз в 2 с
# (владелец 10.10: «пнл как можно чаще»), плюс состояние и журнал.
RATE = {"read": (600, 60.0), "write": (10, 60.0)}    # (запросов, окно с)
STAGE_NOT_BUILT = "not built yet"
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


def best_of(d, dep):
    """Лучшие сделки на депозите для главной сайта (владелец 16.10): список
    отобран прогонами книг по деньгам НЕТТО и сведён сборщиком
    (`rules.best_trades`/`merge_best`); здесь только подписи книги из
    линеек свода. Нет поля в своде — None («не измерено», не пустой топ).
    Рядом объём выборки и число убыточных: топ без знаменателя был бы
    отбором лучшего, выданным за типичное."""
    blk = (d.get("best") or {}).get(str(int(float(dep))))
    if not isinstance(blk, dict):
        return None
    names = {}
    for r in d.get("rulers") or []:
        if isinstance(r, dict) and r.get("key"):
            br = r.get("branch") or {}
            names[r["key"]] = {"title_en": r.get("title_en") or r["key"],
                               "book_side": r.get("side") or "long",
                               "branch_en": (None if br.get("default") is not False else br.get("title_en"))}
    top = [dict(x, **names.get(x.get("book"), {"title_en": x.get("book"), "book_side": None, "branch_en": None}))
           for x in blk.get("top") or []]
    return {"n": blk.get("n"), "n_loss": blk.get("n_loss"), "top": top}


class App:
    """Логика API без HTTP: её гоняют проверки напрямую."""

    def __init__(self, dbpath, pub, operator_token=None, venue=bybit, dca_fetch=None, pub_fetch=None,
                 apple_verify=None, server_ip=SERVER_IP, max_accounts=MAX_ACCOUNTS,
                 out=None, exec_root=None, sender=None):
        self.db = DBM.DB(dbpath)
        self.pub = pub
        self.operator_token = operator_token
        self.venue = venue
        self.dca_fetch = dca_fetch or fetch_dca
        self.pub_fetch = pub_fetch or fetch_pub
        self.apple_verify = apple_verify
        self.server_ip = server_ip
        self._max_accounts = max_accounts
        self.rate = RateLimiter()
        self._dca = {"at": 0.0, "data": None}
        self.out = out or os.path.dirname(dbpath) or "."
        self.exec_root = exec_root or EXEC_ROOT
        self.sender = sender or PUSH.Sender(self.out)
        # подмены источников и баров для проверок; None — настоящие
        self.intents_env = None
        self._intents_at = 0.0
        # журнал намерений пишут двое: такт намерений (фоновый поток) и
        # ручное закрытие (запрос) — `seq` обязан расти без дублей
        self.intents_lock = threading.Lock()

    # ------------------------------------------------------------ вход
    def auth_operator(self, token, device=None):
        if not self.operator_token or not token or token != self.operator_token:
            return 403, {"error": "operator token rejected"}
        op = self.db.operator()
        if op is None:
            aid = self.db.create_account("operator")
            self.db.event(aid, "account", "operator account created")
        else:
            aid = op["id"]
        tok = self.db.new_session(aid, device)
        self.db.event(aid, "auth", "operator sign-in", {"device": device})
        return 200, {"session": tok, "account_id": aid, "role": "operator"}

    def auth_apple(self, identity_token, device=None, current=None):
        if self.apple_verify is None:
            return 503, {"error": "Sign in with Apple is not configured on the server"}
        try:
            who = self.apple_verify(identity_token or "")
        except ValueError as e:
            # Причина — в журнал процесса (без токена): отказ, которого не
            # видно ни в журнале, ни на телефоне, стоил вечера 09.10.
            log("вход через Apple отвергнут:", str(e))
            return 401, {"error": str(e)}
        except Exception as e:                                 # noqa: BLE001
            log("вход через Apple: сбой проверки:", type(e).__name__, str(e)[:200])
            return 503, {"error": f"Apple sign-in check failed: {type(e).__name__}"}
        acc = self.db.account_by_apple(who["sub"])
        if acc is None and current is not None and not current["apple_sub"]:
            # оператор привязывает свой Apple ID к уже существующему аккаунту
            self.db.link_apple(current["id"], who["sub"], who.get("email"))
            acc = self.db.account(current["id"])
            self.db.event(acc["id"], "account", "Apple ID linked to the account")
        if acc is None:
            if self.db.accounts_count() >= self.max_accounts:
                log(f"регистрация отвергнута: аккаунтов {self.db.accounts_count()} при пределе {self.max_accounts}")
                return 403, {"error": "Registration is closed for now: all places are taken. Please try again later."}
            role = "operator" if self.db.accounts_count() == 0 else "user"
            aid = self.db.create_account(role, who["sub"], who.get("email"))
            self.db.event(aid, "account", f"account created ({role})")
            acc = self.db.account(aid)
        if acc["status"] != "active":
            return 403, {"error": "this account is suspended"}
        tok = self.db.new_session(acc["id"], device)
        self.db.event(acc["id"], "auth", "signed in with Apple", {"device": device})
        return 200, {"session": tok, "account_id": acc["id"], "role": acc["role"]}

    def logout(self, token):
        self.db.drop_session(token)
        return 200, {"ok": True}

    def me(self, acc):
        return 200, {"account_id": acc["id"], "role": acc["role"], "email": acc["email"],
                     "apple_linked": bool(acc["apple_sub"]), "schema": SCHEMA,
                     "consent": self.consent_state(acc)}

    # ------------------------------------------------------------ пределы и согласие
    @property
    def max_accounts(self):
        """Предел аккаунтов: файл оператора, иначе число из конструктора."""
        try:
            with open(os.path.join(self.out or "", "limits.json"), encoding="utf-8") as f:
                return int(json.load(f).get("max_accounts"))
        except (OSError, ValueError, TypeError):
            return self._max_accounts

    def set_limits(self, acc, max_accounts):
        if acc["role"] != "operator":
            return 403, {"error": "operator only"}
        try:
            n = int(max_accounts)
        except (TypeError, ValueError):
            return 400, {"error": "max_accounts must be an integer"}
        if n < 1:
            return 400, {"error": "max_accounts must be at least 1 (the operator is the first account)"}
        if not self.out:
            return 503, {"error": "the server has no out directory"}
        with open(os.path.join(self.out, "limits.json"), "w", encoding="utf-8") as f:
            json.dump({"max_accounts": n, "at": time.time(), "by": acc["id"]}, f)
        self.db.event(acc["id"], "operator", f"account limit: {n}")
        return 200, {"max_accounts": n, "accounts": self.db.accounts_count()}

    def limits(self, acc):
        if acc["role"] != "operator":
            return 403, {"error": "operator only"}
        return 200, {"max_accounts": self.max_accounts, "accounts": self.db.accounts_count()}

    # ------------------------------------------------------------ сайт
    TOP_DEPOSIT = 1000.0

    def top(self, deposit=None):
        """Главная сайта: лучшая стратегия и рейтинг на одном депозите.

        Правило отбора объявлено и отдаётся словами: наибольший доход за
        всю запись (с бэктестом — умолчание владельца 14.10) на депозите
        1 000 $, сложный процент. Это витрина прошлых результатов, не
        выбор книги; рядом — запись вперёд и её дата. Кривая — накопленная
        сумма дневного ряда сервера на депозит: та же формула, что у итога
        (`final = Σ usd / deposit`), ничего другого страница не считает."""
        d = self.dca() or {}
        deposits = [float(x) for x in (d.get("deposits") or [])]
        dep = self.TOP_DEPOSIT
        if deposit is not None:
            try:
                dep = float(deposit)
            except (TypeError, ValueError):
                return 400, {"error": "deposit must be a number"}
            if deposits and dep not in deposits:
                return 400, {"error": "deposit must be one of " + ", ".join(f"{x:g}" for x in deposits)}
        rows = []
        for r in d.get("rulers") or []:
            key = r.get("key") if isinstance(r, dict) else r
            b = (d.get("books") or {}).get(self.cell_key(key, dep)) or {}
            st = b.get("all") or {}
            if not key or not st or not st.get("n"):
                continue
            fw = b.get("forward") or {}
            rows.append({"book": key, "title_en": r.get("title_en") or key, "side": r.get("side") or "long",
                         "plain": r.get("plain_en_short") or "", "deposit": dep,
                         # адрес в дереве (спека 18) — для главной: режим → сторона → ветвь
                         "branch_en": ((r.get("branch") or {}).get("title_en") if isinstance(r.get("branch"), dict) else None),
                         "branch_default": (r.get("branch") or {}).get("default") is not False if isinstance(r.get("branch"), dict) else True,
                         "final": st.get("final"), "max_dd": st.get("max_dd"), "n": st.get("n"),
                         "max_dd_usd": st.get("max_dd_usd"), "open_dd": st.get("open_dd"),
                         "win": st.get("win"), "usd": st.get("usd"),
                         "forward_final": fw.get("final"), "forward_n": fw.get("n"), "forward_since": b.get("forward_since"),
                         "open_n": len(((b.get("open") or {}).get("positions") or [])),
                         "open_dd_share": st.get("open_dd_share"), "open_dd_at": st.get("open_dd_at"),
                         "_open": st.get("open_days"),
                         "_days": st.get("days_rows") or []})
        rows.sort(key=lambda x: (x["final"] is None, -(x["final"] or 0)))
        top = None
        if rows:
            t = rows[0]
            series, dips = top_series(t["_days"], t["_open"], dep)
            top = {k: v for k, v in t.items() if k not in ("_days", "_open")}
            top["days"] = series
            top["days_n"] = len(series)
            # Просадка открытых по дням: точка = закрытый итог дня + худшая
            # почасовая отметка открытых в этот день, доля депозита; дня без
            # отметки под водой нет (None) — «не было в минусе», не ноль.
            # Ряд не передан артефактом (прежний образец) — поля нет вовсе.
            top["open_dips"] = dips
        for x in rows:
            x.pop("_days", None)
            x.pop("_open", None)
        return 200, {"rule": f"Ranked by return over the whole record at a ${dep:,.0f} deposit, compound sizing. "
                             "A showcase of past results, not a forecast.",
                     "deposit": dep, "deposits": deposits, "top": top, "ranking": rows, "stale": bool(d.get("stale")),
                     "best": best_of(d, dep),
                     "window": d.get("window"), "computed_at": computed_at_of(d)}

    def site(self):
        d = site_settings(self.out)
        d["server_ip"] = self.server_ip
        d["host"] = SITE_HOST
        return 200, d

    def set_site(self, acc, body):
        if acc["role"] != "operator":
            return 403, {"error": "operator only"}
        cur = site_settings(self.out)
        for k in SITE_KEYS:
            if k not in body:
                continue
            v = str(body.get(k) or "").strip()
            if k == "apple_client_id" and not SITE_ID.match(v):
                return 400, {"error": "apple_client_id: letters, digits, dots, dashes only"}
            if k.endswith("_url") and v and not v.startswith("https://"):
                return 400, {"error": f"{k} must start with https://"}
            if len(v) > 300:
                return 400, {"error": f"{k} is too long"}
            cur[k] = v
        with open(os.path.join(self.out, "site.json"), "w", encoding="utf-8") as f:
            json.dump(cur, f, ensure_ascii=False, indent=1)
        self.db.event(acc["id"], "operator", "site settings saved", {k: cur[k] for k in SITE_KEYS})
        return self.site()

    def overview(self, acc):
        """Оператору: аккаунты с числом ключей и подписок, согласие; ёмкость
        по ячейкам (спека 15 §7a.5 — измеритель ёмкости до второго аккаунта)."""
        if acc["role"] != "operator":
            return 403, {"error": "operator only"}
        accs = []
        cells = {}
        for a in self.db.c.execute("SELECT * FROM accounts ORDER BY created").fetchall():
            subs = self.db.subscriptions_of(a["id"])
            last = self.db.last_consent(a["id"])
            accs.append({"account_id": a["id"], "role": a["role"], "email": a["email"], "created": a["created"],
                         "status": a["status"], "keys": len(self.db.keys_of(a["id"])), "subs": len(subs),
                         "live": sum(1 for x in subs if x["mode"] == "live"),
                         "consent": last["version"] if last else None})
            for x in subs:
                c = cells.setdefault((x["book"], float(x["deposit"])), {"book": x["book"], "deposit": float(x["deposit"]), "live": 0, "dry": 0})
                c["live" if x["mode"] == "live" else "dry"] += 1
        return 200, {"accounts": accs, "cells": sorted(cells.values(), key=lambda c: (c["book"], c["deposit"])),
                     "max_accounts": self.max_accounts}

    def consent_state(self, acc):
        cur = LEGAL.current()
        mine = self.db.consent(acc["id"], cur)
        last = self.db.last_consent(acc["id"])
        return {"current": cur, "ok": mine is not None,
                "accepted": last["version"] if last else None,
                "accepted_at": last["at"] if last else None}

    def accept(self, acc, version, ip=None, device=None):
        bad = LEGAL.check()
        if bad:
            # тексты разошлись с версией — согласие не с тем, что показано
            return 503, {"error": "documents are being updated, try again later"}
        cur = LEGAL.current()
        if version != cur:
            return 409, {"error": f"the documents changed: accept version {cur}", "current": cur}
        self.db.add_consent(acc["id"], cur, ip=ip, device=device)
        self.db.event(acc["id"], "consent", f"accepted documents version {cur}", {"ip": ip, "device": device})
        return 200, {"consent": self.consent_state(acc)}

    def need_consent(self, acc):
        """Отказ словами, если клиент не принял ТЕКУЩИЕ документы. Оператор —
        владелец сервиса, а не клиент: гейт к нему не относится."""
        if acc["role"] == "operator":
            return None
        if self.db.consent(acc["id"], LEGAL.current()) is not None:
            return None
        return 403, {"error": "Accept the Terms of Use and the Risk Disclosure first "
                              f"(version {LEGAL.current()}).", "consent_required": True}

    # ------------------------------------------------------------ ключи
    def add_key(self, acc, venue, key, secret):
        gate = self.need_consent(acc)
        if gate:
            return gate
        if venue != "bybit":
            return 400, {"error": "exchange not supported: Bybit only"}
        key = (key or "").strip()
        secret = (secret or "").strip()
        if len(key) < 8 or len(secret) < 8:
            return 400, {"error": "API key and secret are required"}
        try:
            info = self.venue.query_api(key, secret)
        except bybit.VenueError as e:
            return 400, {"error": f"the exchange rejected the key: {e}"}
        j = bybit.judge_permissions(info, self.server_ip)
        if j["money_moving"]:
            return 400, {"error": "this key can withdraw or transfer funds "
                                  f"({', '.join(j['money_moving'])}): revoke it and create one without withdrawal rights",
                         "perms": j}
        if not j["trade_ok"]:
            return 400, {"error": "the key has no contract trading permission (ContractTrade: Order, Position)"
                                  + (" — it is read-only" if j["read_only"] else ""), "perms": j}
        warnings = []
        if not j["ip_restricted"]:
            warnings.append("the key has no IP restriction: add the server address "
                            f"{self.server_ip} in the key settings at the exchange")
        elif not j["ip_ok"]:
            warnings.append(f"the key’s IP restriction does not include the server address {self.server_ip}: "
                            "the executor’s requests will be rejected")
        equity = None
        try:
            equity = self.venue.wallet_equity(key, secret)
        except bybit.VenueError as e:
            warnings.append(f"account equity not read: {e}")
        modes = {}
        try:
            modes = self.venue.position_mode(key, secret)
        except bybit.VenueError as e:
            warnings.append(f"position mode not read: {e}")
        cipher = sealed.seal(self.pub, json.dumps({"venue": venue, "key": key, "secret": secret}).encode("utf-8"))
        del secret
        perms = dict(j, warnings=warnings, position_modes=modes)
        kid = self.db.add_key(acc["id"], venue, key[:4], cipher, perms, j["ip_ok"], equity)
        self.db.event(acc["id"], "key", f"key {key[:4]}… added", {"key_id": kid, "warnings": warnings})
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
            return 404, {"error": "no such key"}
        if self.db.subs_on_key(kid, live_only=True):
            return 409, {"error": "this key has a live subscription: stop it first"}
        for s in self.db.subs_on_key(kid):
            self.db.close_subscription(s["id"])
        self.db.revoke_key(kid)
        self.db.event(acc["id"], "key", f"key {r['key_prefix']}… revoked, its subscriptions closed")
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
                              # имя режима для людей (14.10): из свода, одним ядром с правилами
                              "title_en": (r.get("title_en") if isinstance(r, dict) else None) or key,
                              # адрес в дереве книг (спека 18): ветвь правил и
                              # основная книга — из свода, одним ядром с правилами
                              "branch": (r.get("branch") if isinstance(r, dict) else None),
                              "base": (((r.get("branch") or {}).get("base") if isinstance(r, dict) else None) or key),
                              # касса БУМАГИ — справка: подписка стартует с депозита (§2)
                              "paper_cash_usd": self.paper_cash(b, float(dep)),
                              "ticket_usd": self.ticket_of(b, float(dep)),
                              "final": ((b.get("all") or {}).get("final")),
                              "n": ((b.get("all") or {}).get("n"))})
        return 200, {"cells": cells, "stale": d.get("stale"), "window": d.get("window"),
                     "sizings": sizings, "sizing_title": d.get("sizing_title") or {},
                     "sizing_plain": d.get("sizing_plain") or {},
                     # дерево книг режим → сторона → ветви — готовое на сервере
                     "tree": (d.get("rules") or {}).get("TREE")}

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
        gate = self.need_consent(acc)
        if gate:
            return gate
        k = self.db.key(key_id, acc["id"])
        if k is None or k["status"] != "ok":
            return 404, {"error": "no such key, or it was revoked"}
        try:
            deposit = float(deposit)
        except (TypeError, ValueError):
            return 400, {"error": "deposit must be one of the listed amounts"}
        st, cells = self.strategies()
        sizing = sizing or DEFAULT_SIZING
        if sizing not in cells["sizings"]:
            return 400, {"error": f"unknown sizing {sizing!r}; known: "
                                  + ", ".join(cells["sizings"])}
        cell = next((c for c in cells["cells"] if c["book"] == book
                     and abs(c["deposit"] - deposit) < 1e-9 and c["sizing"] == sizing), None)
        if cell is None:
            return 400, {"error": f"no strategy {book} with deposit {deposit:g} $ on the server"}
        for s in self.db.subs_on_key(key_id):
            # одна книга на ключ в ЛЮБОМ формате: две подписки одной книги
            # торговали бы одни имена на одном счёте и ломали сверку
            if s["book"] == book:
                return 409, {"error": "this key already has a subscription to this strategy"}
        state = {"side": cell["side"], "sizing": sizing, "warnings": []}
        if cell["side"] == "both":
            try:
                modes = self.venue_modes(k)
                off = sorted(s for s, m in modes.items() if m != "hedge")
                state["hedge_mode"] = "off" if off else ("on" if modes else "n/a")
                state["hedge_off_syms"] = off[:50]
                if off:
                    state["warnings"].append(f"hedge mode is off for {len(off)} symbols — "
                                             "a two-sided strategy cannot trade live")
            except bybit.VenueError as e:
                state["hedge_mode"] = "n/a"
                state["warnings"].append(f"hedge mode not read: {e}")
        sid = self.db.add_subscription(acc["id"], key_id, book, deposit, state)
        self.db.event(acc["id"], "subscription", f"subscribed: {book}, deposit {deposit:g} $, {sizing} (dry run)",
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
            return 404, {"error": "no such subscription"}
        if s["mode"] == "live":
            # Живую подписку закрыть можно, когда у исполнителя нет
            # открытых позиций (владелец 11.10 закрыл всё руками и нажал
            # «Close subscription» — прежде отказ «сперва disarm» уходил в
            # плашку вверху экрана, и кнопка казалась мёртвой). Входы
            # выключаются файлом, исполнитель останавливает сторож
            # (`ladder_run.ensure`: подписка не активна — мягкая остановка).
            ex = self.exec_status(sid)
            if ex is None:
                return 409, {"error": "the executor has not reported its status — cannot see whether positions are closed; try again in a minute"}
            open_ = [p.get("sym") for p in ex.get("positions") or []]
            if open_:
                return 409, {"error": f"{len(open_)} position(s) still open ({', '.join(open_)}): close them with Close and try again"}
            d = self.sub_dir(sid)
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, "NO_ENTRIES"), "w") as f:
                f.write(str(time.time()))
            self.db.c.execute("UPDATE subscriptions SET mode='dry' WHERE id=?", (sid,))
        self.db.close_subscription(sid)
        self.db.event(acc["id"], "subscription", f"subscription {s['book']} closed")
        return 200, {"ok": True, "note": "subscription closed; the executor stops within 5 minutes"}

    # ------------------------------------------------------------ живой режим
    def live_enabled(self):
        return os.path.exists(os.path.join(self.out, "LIVE_ENABLED"))

    def set_live_enabled(self, acc, on):
        """Рубильник оператора (§7a.5): без него ни одна подписка в live
        не переводится. Выключение НЕ останавливает работающих — для
        этого у подписки `disarm` и `kill`."""
        if acc["role"] != "operator":
            return 403, {"error": "operator only"}
        path = os.path.join(self.out, "LIVE_ENABLED")
        if on:
            with open(path, "w") as f:
                f.write(str(time.time()))
        elif os.path.exists(path):
            os.remove(path)
        self.db.event(acc["id"], "live", "live trading switch " + ("ON" if on else "off"))
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
        gate = self.need_consent(acc)
        if gate:
            return gate
        """Перевод подписки в живые сделки — кнопкой владельца (§7a.4).
        Подтверждение — словом `книга:депозит`: случайное нажатие его не
        наберёт. Проверки машиной; любая не прошла — отказ словами."""
        s = self.db.subscription(sid, acc["id"])
        if s is None:
            return 404, {"error": "no such subscription"}
        want = f"{s['book']}:{int(float(s['deposit']))}"
        if (confirm or "").strip() != want:
            return 400, {"error": f"confirmation does not match: type “{want}”"}
        why = []
        if not self.live_enabled():
            why.append("live trading is switched off on the server")
        k = self.db.key(s["key_id"])
        if k is None or k["status"] != "ok":
            why.append("the subscription’s key was revoked")
        others = [o for o in self.db.subs_on_key(s["key_id"], live_only=True) if o["id"] != sid]
        if others:
            why.append(f"this key already has a live subscription ({others[0]['book']}) — two would share the same positions")
        st = json.loads(s["state_json"] or "{}")
        cash = self.sub_cash(s, st)
        if k is not None:
            age = (time.time() - k["equity_at"]) if k["equity_at"] else None
            if k["equity_usd"] is None or age is None or age > 24 * 3600:
                why.append("account equity not measured in the last 24 h — press “Check account”")
            elif k["equity_usd"] < cash:
                why.append(f"the account holds {k['equity_usd']:,.2f} $, the subscription needs {cash:,.2f} $")
        if why:
            self.db.event(acc["id"], "live", f"going live with {s['book']} refused: " + "; ".join(why))
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
        self.db.event(acc["id"], "live", (f"subscription {s['book']} {float(s['deposit']):g} $ is now LIVE"
                                          if was != "live" else f"subscription {s['book']}: entries resumed"),
                      {"subscription_id": sid})
        return 200, {"ok": True, "mode": "live",
                     "note": "the executor starts within 5 minutes; first entries come with the next picks"}

    def disarm(self, acc, sid):
        """Входы выключены, открытые позиции исполнитель ведёт дальше
        (цель, пол, срок, охрана рынком). Режим остаётся live."""
        s = self.db.subscription(sid, acc["id"])
        if s is None:
            return 404, {"error": "no such subscription"}
        if s["mode"] != "live":
            return 409, {"error": "the subscription is not live"}
        d = self.sub_dir(sid)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "NO_ENTRIES"), "w") as f:
            f.write(str(time.time()))
        self.db.event(acc["id"], "live", f"subscription {s['book']}: new entries stopped, open positions are managed")
        return 200, {"ok": True, "entries": False}

    def to_dry(self, acc, sid):
        """Обратно в сухой режим — только без открытых позиций."""
        s = self.db.subscription(sid, acc["id"])
        if s is None:
            return 404, {"error": "no such subscription"}
        ex = self.exec_status(sid) or {}
        if ex.get("positions"):
            return 409, {"error": f"{len(ex['positions'])} position(s) still open: stop entries first and wait until they close"}
        self.db.c.execute("UPDATE subscriptions SET mode='dry' WHERE id=?", (sid,))
        self.db.event(acc["id"], "live", f"subscription {s['book']} back to dry run")
        return 200, {"ok": True, "mode": "dry"}

    def close_position(self, acc, sid, sym, pos_at):
        """Ручное закрытие ОДНОЙ позиции кнопкой владельца (11.10).

        Намерение выхода дописывается в журнал намерений подписки тем же
        писателем, что и выходы охраны рынком (`intents._append`, общий
        `seq`); исполнитель на следующем такте снимает рунги и цель и
        закрывает reduceOnly-IOC с потолком 100 б.п. (`ladder.close`,
        исход «cmd_close»). Позиция определяется ИМЕНЕМ И СЕКУНДОЙ РЕШЕНИЯ:
        исполнитель отвергает выход чужой позиции того же имени."""
        s = self.db.subscription(sid, acc["id"])
        if s is None:
            return 404, {"error": "no such subscription"}
        if s["mode"] != "live":
            return 409, {"error": "the subscription is not live — nothing to close"}
        sym = str(sym or "").upper()
        try:
            pos_at = float(pos_at)
        except (TypeError, ValueError):
            return 400, {"error": "sym and pos_at of the position are required"}
        ex = self.exec_status(sid)
        if ex is None:
            return 409, {"error": "the executor has not reported its status — cannot close through it now"}
        q = next((x for x in ex.get("positions") or []
                  if x.get("sym") == sym and abs(float(x.get("pos_at") or 0) - pos_at) < 1.0), None)
        if q is None:
            return 404, {"error": f"no open position {sym} from this decision"}
        if q.get("closing"):
            return 200, {"ok": True, "already": True, "closing": q.get("closing"),
                         "note": "the position is already closing"}
        row = {"kind": "exit", "sub": sid, "sym": sym, "book": q.get("book"), "side": q.get("side"),
               "decided_at": pos_at, "reason": "manual", "by": acc["id"], "computed_at": time.time()}
        with self.intents_lock:
            seqs = INTENTS._append(INTENTS.intents_path(self.exec_root, sid), [row], seqs=True)
        self.db.event(acc["id"], "live", f"manual close {sym} ({s['book']})",
                      {"subscription_id": sid, "sym": sym, "seq": seqs[0] if seqs else None})
        return 200, {"ok": True, "seq": seqs[0] if seqs else None,
                     "note": "the executor closes the position within about 2 s with a reduce-only order (price limit 1 %)"}

    def kill(self, acc, sid, on):
        """KILL подписки: исполнитель не делает НИЧЕГО (ни заявок, ни отмен)."""
        if acc["role"] != "operator":
            return 403, {"error": "operator only"}
        s = self.db.subscription(sid, acc["id"])
        if s is None:
            return 404, {"error": "no such subscription"}
        d = self.sub_dir(sid)
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, "KILL")
        if on:
            with open(path, "w") as f:
                f.write(str(time.time()))
        elif os.path.exists(path):
            os.remove(path)
        self.db.event(acc["id"], "live", f"subscription {s['book']}: KILL " + ("ON" if on else "lifted"))
        return 200, {"kill": bool(on)}

    def check_account(self, acc, sid, runner=None):
        """Предполётная проверка счёта по кнопке владельца: ключ открывает
        отдельный процесс (`preflight.py`), сюда приходит только текст —
        числа и да/нет, без ключа. Эквити записывается в базу."""
        s = self.db.subscription(sid, acc["id"])
        if s is None:
            return 404, {"error": "no such subscription"}
        cmd = [sys.executable, os.path.join(HERE, "preflight.py"), "--db", self.db.path,
               "--sub", sid, "--update-equity"]
        try:
            r = (runner or (lambda c: subprocess.run(c, capture_output=True, text=True, timeout=60)))(cmd)
            text = (r.stdout or "") + (("\n" + r.stderr[-800:]) if r.stderr else "")
        except Exception as e:                                  # noqa: BLE001
            return 502, {"error": f"the check did not run: {type(e).__name__}"}
        self.db.event(acc["id"], "live", f"account check {s['book']}", {"subscription_id": sid})
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
                    warnings.append(f"the account holds {equity:,.0f} $, the subscription needs {cash:,.0f} $ — no entries until it does")
            else:
                warnings.append("account equity not read")
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
                # слова исполнителя (пауза, последняя ошибка) — по-английски показа
                executor = {"status": ({k: (TRADES.reason_en(ex.get(k)) if k in ("paused", "last_error") else ex.get(k))
                                        for k in ("at_ms", "mode", "kill", "no_entries", "paused",
                                                  "realized_usd", "realized_today_usd", "entries_n",
                                                  "closed_n", "rejects_n", "last_error",
                                                  "margin_open_usd", "hedge")} if ex else None),
                            "age_s": (time.time() - float(ex["at_ms"]) / 1000.0) if ex and ex.get("at_ms") else None,
                            "kill": os.path.exists(os.path.join(d_sub, "KILL")),
                            "no_entries": os.path.exists(os.path.join(d_sub, "NO_ENTRIES")),
                            "why_none": (None if ex else "the executor has not started yet: it starts within 5 minutes")}
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
            return 502, {"error": f"the strategy server did not answer: {e}"}
        return 200, d or {}

    # ------------------------------------------------------------ устройства и пуши (§7.5)
    def add_device(self, acc, token, env="prod", build=None):
        tok = str(token or "").strip().lower()
        if not tok or not all(c in "0123456789abcdef" for c in tok) or len(tok) < 32:
            return 400, {"error": "device token must be an APNs hex string"}
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
            return 403, {"error": "operator only"}
        try:
            r = PUSH.save_config(self.out, team_id, key_id, p8, topic)
        except ValueError as e:
            return 400, {"error": str(e)}
        self.sender._jwt = (0.0, None, None)
        self.db.event(acc["id"], "push", f"APNs key set: {r['key_id']}, topic {r['topic']}")
        return 200, {"ok": True, **r}

    def push_test(self, acc):
        """Пробный пуш на устройства аккаунта — без записи сделки."""
        devs = self.db.devices_of(acc["id"])
        if not devs:
            return 409, {"error": "no registered devices on this account: open the app and allow notifications"}
        if PUSH.load_config(self.out) is None:
            return 409, {"error": "push notifications are not configured on the server yet"}
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
            return 400, {"error": "since and limit must be numbers"}
        mode = (mode or "live").strip()
        modes = None if mode == "all" else [m for m in mode.split(",") if m]
        rows = [TRADES.view(r) for r in self.db.trades_of(acc["id"], since=since, limit=limit, modes=modes)]
        by_mode = {}
        for r in self.db.c.execute("SELECT mode, COUNT(*) AS n FROM trades WHERE account_id=? GROUP BY mode",
                                   (acc["id"],)).fetchall():
            by_mode[r["mode"]] = r["n"]
        live = any(s["mode"] == "live" for s in self.db.subscriptions_of(acc["id"]))
        hidden = sum(n for m, n in by_mode.items() if modes is not None and m not in modes)
        note = ("live trades of the executor on the exchange" if live else
                "no live executor: the subscription is a dry run")
        if hidden:
            note += f"; {hidden} dry-run and test records hidden"
        return 200, {"trades": rows, "by_mode": by_mode, "mode": mode, "hidden": hidden,
                     "executor_running": "live" if live else "dry", "note": note}

    # Слова исхода — те же, что у строк бумажной книги: карточка позиции
    # одна на бумагу и живое, и два словаря однажды разошлись бы.
    EXIT_WORDS = {"take": "target", "floor": "floor", "term": "term", "market": "market guard",
                  "cmd_close": "manual", "liq": "liquidation", "mismatch": "outside the executor"}

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
                p["mark_why"] = ("the executor has not reported its status" if not ex else
                                 "the executor no longer holds this position — the outcome waits for its log record")
                continue
            # закрытие идёт (ручное, срок, пол, недоисполненный выход) —
            # приложение показывает его вместо кнопки
            if q.get("closing"):
                p["closing"] = q.get("closing")
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
        self.attach_paper(out, subs)
        out.sort(key=lambda p: (p["state"] != "open", -float(p.get("exit_ts") or p["at"] or 0)))
        return 200, {"positions": out, "open": sum(1 for p in out if p["state"] == "open"),
                     "closed": sum(1 for p in out if p["state"] == "closed"),
                     "pnl": self.live_pnl(out, subs), "at": time.time()}

    def attach_paper(self, rows, subs):
        """Та же сделка в бумажной книге — СЫРОЙ сигнал (журнал книги без
        издержек): строка ячейки подписки с тем же именем и секундой
        решения. Сравнение (владелец 10.10: «насколько отличие от сырого
        сигнала, проскальзывание и итоговый пнл»):
          * вход и выход — в % цены, знак «+ = хуже для нас»: лонг купил
            дороже / продал дешевле, шорт продал дешевле / откупил дороже;
          * результат бумаги — в долях ЕЁ маржи (`usd / margin`), переведённый
            на живую маржу: у бумаги маржа своя (её касса выросла), и
            доллары двух касс несравнимы, а доля маржи — сравнима;
          * разница = живое нетто − бумага сырая на той же марже: в неё
            входят проскальзывание, комиссии и задержка входа.
        Нет строки бумаги — причина словами, не ноль."""
        d = self.dca() or {}
        books = d.get("books") or {}
        for p in rows:
            book = books.get(p.get("cell") or "") or {}
            cands = list(book.get("trades") or []) + list((book.get("open") or {}).get("positions") or [])
            q = next((x for x in cands if x.get("sym") == p["sym"]
                      and abs(float(x.get("at") or 0) - float(p["pos_at"])) < 1.0), None)
            if q is None:
                # «Считала ли бумага этот час» — по МОМЕНТУ ЕЁ ПРОГОНА
                # (`open.at`), а не по последнему взятому решению: 10.10
                # бумага посчитала 20:00 в 20:59, ничего не взяла (касса),
                # а подпись по последнему входу (15:00) говорила «ещё не
                # считала» — отказ, выданный за ожидание.
                ran = (book.get("open") or {}).get("at")
                if ran is None:
                    p["paper_why"] = "paper run time unknown — nothing to compare with"
                elif float(p["pos_at"]) > float(ran):
                    p["paper_why"] = "the paper book has not computed this hour yet"
                else:
                    p["paper_why"] = "the paper book did not take this decision (cash or one position per symbol)"
                continue
            closed = q.get("exit_ts") is not None and q.get("exit") is not None
            pm = float(q.get("margin") or 0) or None
            if closed:
                frac = (float(q["usd"]) / pm) if (pm and q.get("usd") is not None) else q.get("pnl_frac")
            else:
                frac = (float(q["mark_usd"]) / pm) if (pm and q.get("mark_usd") is not None) else q.get("mark_frac")
            short = (p.get("side") == "short")
            pe, le = q.get("entry_px"), p.get("entry_px")
            entry_cost = None
            if pe and le:
                entry_cost = ((float(pe) - float(le)) if short else (float(le) - float(pe))) / float(pe) * 100.0
            exit_cost = None
            if closed and p["state"] == "closed" and q.get("exit_px") and p.get("exit_px"):
                px, lx = float(q["exit_px"]), float(p["exit_px"])
                exit_cost = ((lx - px) if short else (px - lx)) / px * 100.0
            paper_usd = (float(frac) * float(p["margin"])) if (frac is not None and p.get("margin")) else None
            live_usd = p.get("usd") if p["state"] == "closed" else p.get("mark_usd")
            p["paper"] = {"state": "closed" if closed else "open", "entry_px": pe, "exit_px": q.get("exit_px"),
                          "exit": q.get("exit"), "exit_ts": q.get("exit_ts"), "pnl_frac": frac,
                          "margin": q.get("margin"), "usd_at_live_margin": paper_usd}
            diff = (None if live_usd is None or paper_usd is None else float(live_usd) - paper_usd)
            # Разбор разницы в деньгах (владелец 11.10: «почему такая
            # разница при проскальзывании 0»): цена входа и цена выхода на
            # контрактах живой позиции; выходы РАЗНОГО состояния (одна
            # закрыта, другая нет) — отдельной частью целиком; остаток —
            # комиссии и масштаб маржи.
            walk = p.get("walk") or []
            qty = float(walk[-1].get("qty") or 0.0) if walk else 0.0
            parts = None
            if diff is not None:
                live_closed = p["state"] == "closed"
                if live_closed != closed:
                    parts = {"entry_usd": 0.0, "exit_usd": 0.0, "exit_state_usd": diff, "other_usd": 0.0}
                else:
                    e_usd = (-(entry_cost / 100.0) * float(pe) * qty) if (entry_cost is not None and qty) else 0.0
                    x_usd = (-(exit_cost / 100.0) * float(q["exit_px"]) * qty) if (exit_cost is not None and qty) else 0.0
                    parts = {"entry_usd": e_usd, "exit_usd": x_usd, "exit_state_usd": 0.0,
                             "other_usd": diff - e_usd - x_usd}
            p["vs_paper"] = {"entry_cost_pct": entry_cost, "exit_cost_pct": exit_cost,
                             "live_usd": live_usd, "paper_usd": paper_usd, "diff_usd": diff,
                             "parts": parts}

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
        # те же решения в бумаге — только сопоставленные и с числом у обеих
        pair = [p["vs_paper"] for p in rows if p.get("vs_paper") and p["vs_paper"].get("diff_usd") is not None]
        ec = [v["entry_cost_pct"] for v in (p.get("vs_paper") or {} for p in rows) if v.get("entry_cost_pct") is not None]
        xc = [v["exit_cost_pct"] for v in (p.get("vs_paper") or {} for p in rows) if v.get("exit_cost_pct") is not None]

        def med(xs):
            xs = sorted(xs)
            if not xs:
                return None
            n = len(xs)
            return round(xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2.0, 4)
        parts = {k: round(sum(float((v.get("parts") or {}).get(k) or 0.0) for v in pair), 4)
                 for k in ("entry_usd", "exit_usd", "exit_state_usd", "other_usd")}
        vs = {"matched_n": len(pair), "unmatched_n": sum(1 for p in rows if p.get("paper_why")),
              "live_usd": round(sum(float(v["live_usd"]) for v in pair), 4),
              "paper_usd": round(sum(float(v["paper_usd"]) for v in pair), 4),
              "diff_usd": round(sum(float(v["diff_usd"]) for v in pair), 4),
              # среднее со знаком гасит хуже-лучше друг другом (11.10:
              # «0.00 %» при шести входах хуже) — рядом медиана и выходы
              "entry_cost_pct_mean": (round(sum(ec) / len(ec), 4) if ec else None),
              "entry_cost_pct_median": med(ec), "entry_n": len(ec),
              "entry_worse_n": sum(1 for x in ec if x > 0),
              "exit_cost_pct_mean": (round(sum(xc) / len(xc), 4) if xc else None),
              "exit_cost_pct_median": med(xc), "exit_n": len(xc),
              "exit_state_n": sum(1 for v in pair if (v.get("parts") or {}).get("exit_state_usd")),
              "parts": parts}
        return {"vs_paper": vs, "realized_usd": round(realized, 4), "open_usd": round(open_usd, 4),
                "total_usd": round(total, 4), "deposit_usd": dep,
                "total_pct": (round(total / dep * 100.0, 3) if dep else None),
                # открытый и закрытый результат — каждый своим процентом от
                # депозита: заголовок вкладки показывает ОТКРЫТЫЙ, как биржа
                # (владелец 11.10), итог — строкой ниже
                "open_pct": (round(open_usd / dep * 100.0, 3) if dep else None),
                "realized_pct": (round(realized / dep * 100.0, 3) if dep else None),
                "closed_n": len(closed), "open_n": len(opened), "wins_n": wins,
                "open_unmarked": len(opened) - len(marked),
                "fees_usd": round(sum(float(p.get("fees") or 0.0) for p in rows), 4)}

    def trade_test(self, acc, text=None):
        """Пробная строка журнала → приём → запись → пуш: весь канал одной кнопкой."""
        if acc["role"] != "operator":
            return 403, {"error": "operator only"}
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
            with self.intents_lock:
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

# Свод для приложения без ключа страниц (спека 16 §8b, L1). Ключ страниц
# был вшит в сборку и открывал ВСЕ страницы сборщика (статус, память,
# графики); публичному бинарю его давать нельзя. Здесь — только четыре
# ответа, которые читает приложение, только названные параметры, только
# латиница; ключ страниц добавляет сервер, наружу он не выходит. Ответ
# сборщика отдаётся как есть, байтами (свод в фокусе ≈ 2.6 МБ — разбирать
# и собирать его заново незачем), сжатие — если клиент его принимает.
def top_series(days_rows, open_days, dep):
    """Кривая витрины и просадка открытых на ОДНОЙ оси дней.

    Ось — каждый календарный день от первого до последнего (закрытые и дни
    просадки открытых вместе): прежняя ось шла только по дням с закрытыми
    сделками, и неделя без закрытий сжималась в точку. Закрытый итог в день
    без закрытий переносится с прошлого дня — та же сумма Σ usd / депозит,
    что у итога. `open_days` None (артефакт прежнего образца) — dips None."""
    import datetime as _dt
    real = {}
    for x in days_rows or []:
        if x.get("d"):
            real[x["d"]] = real.get(x["d"], 0.0) + float(x.get("usd") or 0.0)
    opn = {x[0]: float(x[1]) for x in (open_days or []) if len(x) >= 2}
    keys = sorted(set(real) | set(opn))
    if not keys or not dep:
        return [], (None if open_days is None else [])
    d0 = _dt.date.fromisoformat(keys[0])
    d1 = _dt.date.fromisoformat(keys[-1])
    series, dips, cum = [], [], 0.0
    while d0 <= d1:
        k = d0.isoformat()
        cum += real.get(k, 0.0)
        series.append([k, round(cum / dep, 6)])
        dips.append(round((cum + opn[k]) / dep, 6) if k in opn else None)
        d0 += _dt.timedelta(days=1)
    return series, (None if open_days is None else dips)


def computed_at_of(d):
    """Момент последнего пересчёта длинных книг для витрины: свод сборщика
    несёт возраст артефакта в часах (`age_h`), а не метку — метка
    выводится из него к минуте; нет возраста — None, не «сейчас»."""
    try:
        age_h = float(d.get("age_h"))
    except (TypeError, ValueError):
        return None
    return time.strftime("%Y-%m-%d %H:%M", time.gmtime(time.time() - age_h * 3600.0))


PUB_ROUTES = {"dca": ("full", "focus", "dep", "ruler", "sizing"),
              "dca_marks": ("dep", "ruler", "sizing"),
              "dca_trades": ("sym", "book"),
              "candles": ("sym", "hours", "end")}
PUB_VALUE = re.compile(r"^[A-Za-z0-9._:\-]{1,64}$")

# Сайт (спека 16 L4): главная, документы, кабинет — файлы `site/`, те же
# ответы API, что у приложения. Настройки сайта (`out/site.json`) задаёт
# оператор из кабинета: Services ID входа через Apple, ссылки на
# приложения, имя компании. Адрес машины — для белого списка ключа биржи.
SITE_DIR = os.path.join(HERE, "site")
SITE_HOST = "algoth.trade"
SITE_PAGES = {"/": ("index.html", "text/html; charset=utf-8"),
              "/index.html": ("index.html", "text/html; charset=utf-8"),
              "/account": ("account.html", "text/html; charset=utf-8"),
              "/legal": ("legal.html", "text/html; charset=utf-8"),
              "/site.css": ("site.css", "text/css; charset=utf-8"),
              "/site.js": ("site.js", "application/javascript; charset=utf-8"),
              # знак и превью (логотип владельца 15.10): иконка вкладки, иконка
              # на экране iPhone, знак в шапке, карточка для соцсетей
              "/favicon.png": ("favicon.png", "image/png"),
              "/logo-word.png": ("logo-word.png", "image/png"),
              "/apple-touch-icon.png": ("apple-touch-icon.png", "image/png"),
              "/logo-mark.png": ("logo-mark.png", "image/png"),
              "/og.png": ("og.png", "image/png")}
SITE_KEYS = ("apple_client_id", "company", "ios_url", "mac_url", "testflight_url")
SITE_ID = re.compile(r"^[A-Za-z0-9._-]{0,120}$")


def site_settings(out):
    try:
        with open(os.path.join(out, "site.json"), encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        d = {}
    return {k: str(d.get(k) or "") for k in SITE_KEYS}


def site_page(path):
    """(тело, тип) страницы сайта или None; файлы читаются с диска каждый
    раз — их пять, они маленькие, а правка видна без перезапуска."""
    hit = SITE_PAGES.get(path)
    if not hit:
        return None
    try:
        with open(os.path.join(SITE_DIR, hit[0]), "rb") as f:
            return f.read(), hit[1]
    except OSError:
        return None


def pub_query(name, q):
    """Параметры публичного запроса: (dict, None) или (None, слова отказа)."""
    allowed = PUB_ROUTES.get(name)
    if allowed is None:
        return None, "no such data"
    out = {}
    for k, vs in q.items():
        if k not in allowed:
            return None, f"parameter {k!r} is not accepted"
        v = vs[0] if vs else ""
        if not PUB_VALUE.match(v):
            return None, f"parameter {k!r}: letters, digits and ._:- only"
        out[k] = v
    return out, None


def fetch_pub(name, params, gzip_ok=False):
    """Ответ сборщика байтами: (код, тело, Content-Encoding или None)."""
    try:
        with open(PAGE_TOKEN, encoding="utf-8") as f:
            tok = f.read().strip()
    except OSError:
        tok = ""
    req = urllib.request.Request(COLLECTOR + "/" + name + "?" + urllib.parse.urlencode(dict(params, k=tok)))
    if gzip_ok:
        req.add_header("Accept-Encoding", "gzip")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return 200, r.read(), r.headers.get("Content-Encoding")
    except urllib.error.HTTPError as e:
        return e.code, b"", None


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
    # Предел на чтение запроса и запись ответа: клиент, замолчавший посреди
    # запроса, не держит поток вечно.
    timeout = 60
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

    def _send_raw(self, body, encoding=None):
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        if encoding:
            self.send_header("Content-Encoding", encoding)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _pub(self, name, q):
        params, why = pub_query(name, q)
        if why:
            return self._send(400, {"error": why})
        gz = "gzip" in (self.headers.get("Accept-Encoding") or "")
        try:
            code, body, enc = self.app.pub_fetch(name, params, gzip_ok=gz)
        except (OSError, ValueError) as e:
            return self._send(502, {"error": f"the data server is not responding: {e}"})
        if code == 403:
            return self._send(502, {"error": "the data server rejected the server’s page key (out/token.txt)"})
        if code != 200:
            return self._send(502, {"error": f"the data server answered {code}"})
        return self._send_raw(body, enc if gz else None)

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

    def _site(self, u, method):
        """Страницы сайта: www → без www, пять файлов, остальное 404."""
        host = (self.headers.get("Host") or "").split(":")[0].lower()
        if host == "www." + SITE_HOST:
            self.send_response(301)
            self.send_header("Location", f"https://{SITE_HOST}{self.path}")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        page = site_page(u.path) if method == "GET" else None
        if page is None:
            return self._send(404, {"error": "not found"})
        body, ctype = page
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(body)

    def _route(self, method):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        parts = [p for p in u.path.split("/") if p]
        if len(parts) < 3 or parts[0] != "api" or parts[1] != "v1":
            return self._site(u, method)
        who = self.client_address[0]
        kind = "write" if method in ("POST", "DELETE") else "read"
        if not self.app.rate.allow(who, kind):
            return self._send(429, {"error": "too many requests, slow down"})
        rest = parts[2:]
        body = self._body() if method in ("POST", "DELETE") else {}
        if body is None:
            return self._send(400, {"error": "request body is not JSON or is too large"})
        # --- без сессии
        if rest == ["auth", "operator"] and method == "POST":
            return self._send(*self.app.auth_operator(body.get("token"), body.get("device")))
        if rest == ["auth", "apple"] and method == "POST":
            cur, _t = self._acc()
            return self._send(*self.app.auth_apple(body.get("identity_token"), body.get("device"), current=cur))
        if rest == ["health"] and method == "GET":
            return self._send(200, {"ok": True, "schema": SCHEMA})
        if rest == ["pub", "top"] and method == "GET":
            return self._send(*self.app.top(q.get("deposit", [None])[0]))
        if len(rest) == 2 and rest[0] == "pub" and method == "GET":
            return self._pub(rest[1], q)
        if rest == ["legal"] and method == "GET":
            return self._send(200, LEGAL.bundle())
        if rest == ["site"] and method == "GET":
            return self._send(*self.app.site())
        acc, tok = self._acc()
        if acc is None:
            return self._send(401, {"error": "sign-in required"})
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
            if act == "close":
                return self._send(*self.app.close_position(acc, sid, body.get("sym"), body.get("pos_at")))
            if act == "cmd":
                return self._send(501, {"error": STAGE_NOT_BUILT})
        if rest == ["consent"] and method == "POST":
            return self._send(*self.app.accept(acc, body.get("version"), ip=self.client_address[0],
                                               device=body.get("device")))
        if rest == ["operator", "limits"] and method == "GET":
            return self._send(*self.app.limits(acc))
        if rest == ["operator", "site"] and method == "POST":
            return self._send(*self.app.set_site(acc, body))
        if rest == ["operator", "overview"] and method == "GET":
            return self._send(*self.app.overview(acc))
        if rest == ["operator", "limits"] and method == "POST":
            return self._send(*self.app.set_limits(acc, body.get("max_accounts")))
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
        return self._send(404, {"error": "not found"})

    def do_GET(self):                                   # noqa: N802
        self._route("GET")

    def do_POST(self):                                  # noqa: N802
        self._route("POST")

    def do_DELETE(self):                                # noqa: N802
        self._route("DELETE")


class Server(http.server.ThreadingHTTPServer):
    """TLS-рукопожатие — в ПОТОКЕ соединения и с пределом времени.

    Прежде слушающий сокет оборачивался целиком (`wrap_socket` на нём), и
    рукопожатие шло внутри `accept()` главного потока: одно соединение,
    открытое и замолчавшее (сканер порта, обрыв мобильной сети), держало
    приём ВСЕХ остальных. 11.10 ночью API так стоял часами при живом
    процессе — сторож видел процесс и молчал, приложение писало «не
    отвечает». Теперь главный поток только принимает TCP, а рукопожатие и
    чтение запроса идут в потоке соединения с пределами `HANDSHAKE_S` и
    `Handler.timeout`.
    """
    daemon_threads = True
    allow_reuse_address = True
    tls = None                  # ssl.SSLContext; None — без TLS (проверки)
    HANDSHAKE_S = 10

    def finish_request(self, request, client_address):
        if self.tls is None:
            return super().finish_request(request, client_address)
        request.settimeout(self.HANDSHAKE_S)
        try:
            conn = self.tls.wrap_socket(request, server_side=True)
        except (ssl.SSLError, OSError):
            return              # сырой сокет закроет `shutdown_request`
        try:
            super().finish_request(conn, client_address)
        finally:
            self.shutdown_request(conn)


def make_server(app, host="0.0.0.0", port=443, tls_dir=None):
    Handler.app = app
    srv = Server((host, port), Handler)
    if tls_dir:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.load_cert_chain(os.path.join(tls_dir, "cert.pem"), os.path.join(tls_dir, "key.pem"))
        srv.tls = ctx
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
