#!/usr/bin/env python3
"""Проверки API приложения (спека 15 Y0): конверт открывается только
приватной половиной и ломается от подмены; вердикт по правам ключа;
вход оператора и предел аккаунтов; ключ с правом вывода отвергается,
секрет не попадает ни в ответ, ни в базу; подписка только на существующую
ячейку, у двусторонней — предупреждение о хедже; состояние считает
эквити против кассы ячейки; адреса этапов Y3–Y4 отвечают «не построен»;
init идемпотентен."""
import http.client
import json
import os
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import sealed                                                 # noqa: E402
import bybit                                                  # noqa: E402
import server as SV                                           # noqa: E402
import init as INIT                                           # noqa: E402
import apple as APPLE                                         # noqa: E402

SECRET = "s3cr3t-never-shown-xyz"
DCA = {"rulers": [{"key": "optimal_h", "title": "оптимальная (шорт)", "side": "short"},
                  {"key": "pair_optimal", "title": "общий счёт", "side": "both"},
                  {"key": "optimal", "title": "оптимальная"}],
       "deposits": [100.0, 1000.0, 10000.0],
       "books": {"optimal_h:1000": {"all": {"usd": 123.4, "final": 0.12, "n": 50}},
                 "pair_optimal:1000": {"all": {"usd": -20.0, "final": -0.02, "n": 10}},
                 "optimal:100": {"all": {"usd": 5.0, "final": 0.05, "n": 3}},
                 # сестра фиксированного билета — свой ключ, свои деньги
                 "pair_optimal:1000:fixed": {"all": {"usd": 7.5, "final": 0.0075, "n": 9}}},
       "sizings": ["compound", "fixed"],
       "sizing_title": {"compound": "сложный процент", "fixed": "фиксированный билет"},
       "window": {"from": "2026-08-08"}, "stale": False}


class FakeVenue:
    def __init__(self, perms=None, ips=None, read_only=0, equity=1500.0, modes=None, fail=None):
        self.perms = perms if perms is not None else {"ContractTrade": ["Order", "Position"]}
        self.ips = ips if ips is not None else ["116.203.146.99"]
        self.read_only = read_only
        self.equity = equity
        self.modes = modes if modes is not None else {"BTCUSDT": "hedge"}
        self.fail = fail
        self.calls = []

    def query_api(self, key, secret):
        self.calls.append(("query", key[:4]))
        if self.fail == "query":
            raise bybit.VenueError("ключ отвергнут")
        return {"permissions": self.perms, "ips": self.ips, "readOnly": self.read_only}

    def wallet_equity(self, key, secret):
        if self.fail == "equity":
            raise bybit.VenueError("нет баланса")
        return self.equity

    def position_mode(self, key, secret, symbols=None):
        return dict(self.modes)


def _app(tmp, venue=None, **kw):
    pem, pub = sealed.keygen()
    fetch = kw.pop("dca_fetch", lambda full=None: DCA)
    app = SV.App(os.path.join(tmp, "app.sqlite"), pub, operator_token="OPTOKEN",
                 venue=venue or FakeVenue(), dca_fetch=fetch, **kw)
    return app, pem


def test_sealed_box_opens_only_with_private_half_and_detects_tamper():
    pem, pub = sealed.keygen()
    pem2, _ = sealed.keygen()
    blob = sealed.seal(pub, b"key:secret")
    assert sealed.open_box(pem, blob) == b"key:secret"
    for bad in (pem2,):
        try:
            sealed.open_box(bad, blob)
            raise AssertionError("чужая половина открыла конверт")
        except Exception as e:                            # noqa: BLE001
            assert not isinstance(e, AssertionError)
    tampered = blob[:-1] + bytes([blob[-1] ^ 1])
    try:
        sealed.open_box(pem, tampered)
        raise AssertionError("подмена не замечена")
    except Exception as e:                                # noqa: BLE001
        assert not isinstance(e, AssertionError)
    with tempfile.TemporaryDirectory() as tmp:
        assert sealed.write_keypair(tmp) is True and sealed.write_keypair(tmp) is False
        assert oct(os.stat(os.path.join(tmp, "master.key")).st_mode & 0o777) == "0o600"
        assert len(sealed.read_pub(tmp)) == 32


def test_permission_judgement():
    j = bybit.judge_permissions({"permissions": {"ContractTrade": ["Order", "Position"]}, "ips": ["1.2.3.4"]}, "1.2.3.4")
    assert j["trade_ok"] and j["ip_ok"] and j["ip_restricted"] and not j["money_moving"]
    j = bybit.judge_permissions({"permissions": {"ContractTrade": ["Order"]}, "ips": []}, "1.2.3.4")
    assert not j["trade_ok"] and not j["ip_restricted"] and not j["ip_ok"]
    j = bybit.judge_permissions({"permissions": {"ContractTrade": ["Order", "Position"], "Wallet": ["Withdraw", "AccountTransfer"]},
                                 "ips": ["*"], "readOnly": 1}, "1.2.3.4")
    assert j["money_moving"] == ["AccountTransfer", "Withdraw"] and j["read_only"] and not j["trade_ok"]


def test_operator_login_account_cap_and_apple_link():
    with tempfile.TemporaryDirectory() as tmp:
        app, _pem = _app(tmp, apple_verify=lambda t: {"sub": "apple-" + t, "email": t + "@x"})
        st, r = app.auth_operator("wrong")
        assert st == 403
        st, r = app.auth_operator("OPTOKEN", "iphone")
        assert st == 200 and r["role"] == "operator" and app.db.accounts_count() == 1
        acc = app.db.account(r["account_id"])
        # второй аккаунт через Apple — закрыто (MAX_ACCOUNTS = 1)
        st, r2 = app.auth_apple("someone", current=None)
        assert st == 403 and "регистрация закрыта" in r2["error"]
        # оператор привязывает свой Apple ID к своему аккаунту — тот же аккаунт
        st, r3 = app.auth_apple("owner", current=acc)
        assert st == 200 and r3["account_id"] == acc["id"] and app.db.accounts_count() == 1
        assert app.db.account(acc["id"])["apple_sub"] == "apple-owner"
        # и дальше входит через Apple без токена оператора
        st, r4 = app.auth_apple("owner", current=None)
        assert st == 200 and r4["account_id"] == acc["id"]
        st, me = app.me(app.db.account(acc["id"]))
        assert me["apple_linked"] is True and me["role"] == "operator"
        assert app.db.session(r4["session"]) is not None
        app.logout(r4["session"])
        assert app.db.session(r4["session"]) is None


def _login(app):
    st, r = app.auth_operator("OPTOKEN")
    return app.db.account(r["account_id"])


def test_key_add_rejects_money_moving_and_readonly_warns_on_ip_and_hides_secret():
    with tempfile.TemporaryDirectory() as tmp:
        app, pem = _app(tmp, venue=FakeVenue(perms={"ContractTrade": ["Order", "Position"], "Wallet": ["Withdraw"]}))
        acc = _login(app)
        st, r = app.add_key(acc, "bybit", "ABCD1234KEY", SECRET)
        assert st == 400 and "выводить" in r["error"] and not app.db.keys_of(acc["id"])
        app.venue = FakeVenue(read_only=1)
        st, r = app.add_key(acc, "bybit", "ABCD1234KEY", SECRET)
        assert st == 400 and "только на чтение" in r["error"]
        app.venue = FakeVenue(ips=[], equity=250.0, modes={"ETHUSDT": "oneway"})
        st, r = app.add_key(acc, "bybit", "ABCD1234KEY", SECRET)
        assert st == 200 and r["prefix"] == "ABCD" and r["trade_ok"] and not r["ip_restricted"]
        assert any("нет IP-ограничения" in w for w in r["warnings"]) and r["equity_usd"] == 250.0
        assert SECRET not in json.dumps(r)
        # в базе — только конверт; открыть его может лишь приватная половина
        row = app.db.key(r["key_id"])
        assert SECRET not in (row["perms_json"] + row["key_prefix"])
        assert SECRET.encode() not in row["cipher"]
        opened = json.loads(sealed.open_box(pem, row["cipher"]))
        assert opened["secret"] == SECRET and opened["key"] == "ABCD1234KEY"
        st, lst = app.list_keys(acc)
        assert len(lst["keys"]) == 1 and SECRET not in json.dumps(lst)
        # ключ с IP не нашим — предупреждение другое
        app.venue = FakeVenue(ips=["9.9.9.9"])
        st, r2 = app.add_key(acc, "bybit", "EFGH5678KEY", SECRET)
        assert st == 200 and any("не содержит адрес сервера" in w for w in r2["warnings"]) and r2["ip_ok"] is False
        # биржа не ответила — отказ словами
        app.venue = FakeVenue(fail="query")
        st, r3 = app.add_key(acc, "bybit", "ZZZZ9999KEY", SECRET)
        assert st == 400 and "не прошёл проверку" in r3["error"]
        # отзыв: конверт стирается
        st, d = app.delete_key(acc, r["key_id"])
        assert st == 200 and app.db.key(r["key_id"])["cipher"] is None
        assert len(app.list_keys(acc)[1]["keys"]) == 1


def test_subscriptions_cells_hedge_warning_and_state():
    with tempfile.TemporaryDirectory() as tmp:
        app, _ = _app(tmp, venue=FakeVenue(equity=1100.0, modes={"BTCUSDT": "hedge", "ETHUSDT": "oneway"}))
        acc = _login(app)
        st, cells = app.strategies()
        assert st == 200 and len(cells["cells"]) == 9 * len(cells["sizings"])
        assert cells["sizings"][0] == "compound"
        c = next(x for x in cells["cells"] if x["book"] == "optimal_h" and x["deposit"] == 1000.0
                 and x["sizing"] == "compound")
        assert c["side"] == "short" and abs(c["paper_cash_usd"] - 1123.4) < 1e-9
        assert next(x for x in cells["cells"] if x["book"] == "optimal" and x["deposit"] == 10000.0
                    and x["sizing"] == "compound")["paper_cash_usd"] is None
        st, k = app.add_key(acc, "bybit", "ABCD1234KEY", SECRET)
        kid = k["key_id"]
        st, r = app.add_subscription(acc, kid, "optimal_h", 7777)
        assert st == 400 and "нет среди книг" in r["error"]
        st, r = app.add_subscription(acc, "key_nope", "optimal_h", 1000)
        assert st == 404
        st, r = app.add_subscription(acc, kid, "optimal_h", 1000, sizing="martingale")
        assert st == 400 and "формат размера" in r["error"]
        st, s1 = app.add_subscription(acc, kid, "optimal_h", 1000)
        assert st == 200 and s1["mode"] == "dry" and s1["side"] == "short" and s1["hedge_mode"] == "n/a"
        assert s1["sizing"] == "compound"             # умолчание — как у бумаги
        st, dup = app.add_subscription(acc, kid, "optimal_h", "1000")
        assert st == 409
        st, s2 = app.add_subscription(acc, kid, "pair_optimal", 1000, sizing="fixed")
        assert st == 200 and s2["side"] == "both" and s2["hedge_mode"] == "off"
        assert s2["sizing"] == "fixed"
        assert any("хеджирования выключен" in w for w in s2["warnings"])
        st, stt = app.state(acc)
        subs = {x["book"]: x for x in stt["subscriptions"]}
        a = subs["optimal_h"]
        # касса подписки — стартовый депозит, не касса бумаги (решение 2026-10-09)
        assert a["cash_usd"] == 1000.0 and a["paper_cash_usd"] == 1123.4 and a["realized_usd"] == 0.0
        assert a["equity_usd"] == 1100.0 and a["equity_ok"] is True and a["idle_usd"] == 100.0
        b = subs["pair_optimal"]
        # касса бумаги — у СЕСТРЫ фиксированного билета, не у сложного процента
        assert b["sizing"] == "fixed" and b["cash_usd"] == 1000.0 and b["equity_ok"] is True
        assert b["paper_cash_usd"] == 1000.0 + 7.5, b
        # живой реализованный результат подписки двигает ЕЁ кассу
        app.db.set_sub_state(a["subscription_id"], {"side": "short", "realized_usd": 150.0})
        st, stt = app.state(acc)
        a2 = {x["book"]: x for x in stt["subscriptions"]}["optimal_h"]
        assert a2["cash_usd"] == 1150.0 and a2["equity_ok"] is False
        assert abs(a2["shortfall_usd"] - 50.0) < 1e-9 and any("подписка требует" in w for w in a2["warnings"])
        assert b["hedge_mode"] == "off" and a["min_order_share"] is None
        assert stt["live_enabled"] is False and len(stt["events_tail"]) >= 3
        st, ev = app.events(acc, 0)
        kinds = [e["kind"] for e in ev["events"]]
        assert "key" in kinds and "subscription" in kinds and SECRET not in json.dumps(ev)
        # удалить ключ с подписками — подписки закрываются
        st, _ = app.delete_key(acc, kid)
        assert st == 200 and app.list_subscriptions(acc)[1]["subscriptions"] == []


def _http(port, method, path, body=None, token=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    c.request(method, path, body=json.dumps(body) if body is not None else None, headers=headers)
    r = c.getresponse()
    data = json.loads(r.read().decode("utf-8"))
    c.close()
    return r.status, data


def test_http_routing_auth_and_stage_gates():
    with tempfile.TemporaryDirectory() as tmp:
        app, _ = _app(tmp)
        srv = SV.make_server(app, host="127.0.0.1", port=0, tls_dir=None)
        port = srv.server_address[1]
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        try:
            assert _http(port, "GET", "/api/v1/health")[0] == 200
            assert _http(port, "GET", "/api/v1/me")[0] == 401
            assert _http(port, "GET", "/nope")[0] == 404
            st, r = _http(port, "POST", "/api/v1/auth/operator", {"token": "OPTOKEN", "device": "test"})
            assert st == 200
            tok = r["session"]
            assert _http(port, "GET", "/api/v1/me", token=tok)[1]["role"] == "operator"
            st, k = _http(port, "POST", "/api/v1/keys", {"key": "ABCD1234KEY", "secret": SECRET}, token=tok)
            assert st == 200 and SECRET not in json.dumps(k)
            st, s = _http(port, "POST", "/api/v1/subscriptions", {"key_id": k["key_id"], "book": "optimal_h", "deposit": 1000}, token=tok)
            assert st == 200
            # перевод в live без подтверждения словом — отказ, не 501
            code, body = _http(port, "POST", f"/api/v1/subscriptions/{s['subscription_id']}/arm", {}, token=tok)
            assert code == 400 and "подтверждение" in body["error"], (code, body)
            assert _http(port, "POST", f"/api/v1/subscriptions/{s['subscription_id']}/cmd", {}, token=tok)[0] == 501
            assert _http(port, "POST", "/api/v1/cmd", {"cmd": "kill"}, token=tok)[0] == 501
            assert _http(port, "GET", "/api/v1/books", token=tok)[1]["deposits"] == [100.0, 1000.0, 10000.0]
            st, stt = _http(port, "GET", "/api/v1/state", token=tok)
            assert st == 200 and stt["subscriptions"][0]["book"] == "optimal_h"
            assert _http(port, "DELETE", f"/api/v1/subscriptions/{s['subscription_id']}", {}, token=tok)[0] == 200
            # предел частоты записи: 10 в минуту
            codes = [_http(port, "POST", "/api/v1/auth/operator", {"token": "x"})[0] for _ in range(12)]
            assert 429 in codes
            assert _http(port, "POST", "/api/v1/auth/logout", {}, token=tok)[0] in (200, 429)
        finally:
            srv.shutdown()


def test_init_is_idempotent_and_prints_pin():
    with tempfile.TemporaryDirectory() as tmp:
        pin1 = INIT.main(out=tmp, ip="127.0.0.1")
        pin2 = INIT.main(out=tmp, ip="127.0.0.1")
        assert pin1 == pin2 and len(pin1) == 44
        for name in ("master.key", "operator_token.txt", "tls/key.pem"):
            assert oct(os.stat(os.path.join(tmp, name)).st_mode & 0o777) == "0o600", name
        assert os.path.exists(os.path.join(tmp, "tls", "cert.pem"))


def test_apple_verify_names_the_audience_and_accepts_listed_ones():
    import jwt
    from cryptography.hazmat.primitives.asymmetric import rsa
    from jwt.algorithms import RSAAlgorithm
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(RSAAlgorithm.to_jwk(key.public_key()))
    jwk["kid"] = "k1"
    now = int(__import__("time").time())
    tok = jwt.encode({"iss": APPLE.ISSUER, "aud": "pl.other.app", "sub": "u1", "exp": now + 600, "iat": now},
                     key, algorithm="RS256", headers={"kid": "k1"})
    try:
        APPLE.verify(tok, audience=["pl.mdsauto.algoth"], keys=[jwk])
        raise AssertionError("чужая аудитория принята")
    except ValueError as e:
        assert "pl.other.app" in str(e) and "pl.mdsauto.algoth" in str(e), e
    who = APPLE.verify(tok, audience=["pl.mdsauto.algoth", "pl.other.app"], keys=[jwk])
    assert who["sub"] == "u1"
    with tempfile.TemporaryDirectory() as tmp:
        f = os.path.join(tmp, "a.txt")
        open(f, "w").write("# комментарий\npl.other.app\n")
        assert APPLE.audiences(f) == ["pl.mdsauto.algoth", "pl.other.app"]


def _ec_pem():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    k = ec.generate_private_key(ec.SECP256R1())
    priv = k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                           serialization.NoEncryption()).decode()
    pub = k.public_key().public_bytes(serialization.Encoding.PEM,
                                      serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    return priv, pub


def test_push_key_is_checked_by_signing_and_words_come_from_the_record():
    """Ключ APNs принимается только если им можно подписать; слова пуша —
    из записи сделки, деньги печатаются, а не считаются."""
    import jwt
    import push as PUSH
    with tempfile.TemporaryDirectory() as tmp:
        priv, pub = _ec_pem()
        try:
            PUSH.save_config(tmp, "TEAM123456", "KEY1234567", "-----BEGIN PRIVATE KEY-----\nнет\n-----END PRIVATE KEY-----")
            assert False, "битый ключ принят"
        except ValueError as e:
            assert "не подписывает" in str(e)
        try:
            PUSH.save_config(tmp, "", "K", priv)
            assert False
        except ValueError:
            pass
        assert PUSH.load_config(tmp) is None and PUSH.public_config(tmp) == {"configured": False}
        r = PUSH.save_config(tmp, "TEAM123456", "KEY1234567", priv)
        assert r["key_id"] == "KEY1234567" and r["topic"] == "pl.mdsauto.algoth" and r["team_id"] == "TEA…"
        assert oct(os.stat(PUSH.config_path(tmp)).st_mode)[-3:] == "600"
        cfg = PUSH.load_config(tmp)
        tok = PUSH.jwt_for(cfg["team_id"], cfg["key_id"], cfg["p8"], now=1_700_000_000)
        claims = jwt.decode(tok, pub, algorithms=["ES256"])
        assert claims == {"iss": "TEAM123456", "iat": 1_700_000_000}
        assert jwt.get_unverified_header(tok)["kid"] == "KEY1234567"
        assert PUSH.public_config(tmp)["configured"] is True and "p8" not in PUSH.public_config(tmp)
        # тема задаётся явно и переживает замену ключа без темы
        assert PUSH.save_config(tmp, "TEAM123456", "KEY1234567", priv, topic="algoth")["topic"] == "algoth"
        assert PUSH.save_config(tmp, "TEAM123456", "KEY7654321", priv)["topic"] == "algoth"
        assert PUSH.load_config(tmp)["key_id"] == "KEY7654321"
        # слова
        t = {"kind": "entry", "mode": "live", "sym": "KAITOUSDT", "side": "long", "margin_usd": 25.0,
             "lev": 4.0, "px": 1.2345, "subscription_id": "sub_1", "id": 7}
        pl = PUSH.payload_for(t, book="optimal · 100 $")
        al = pl["aps"]["alert"]
        assert al["title"] == "Entry · KAITO long" and al["body"] == "25.00 $ · ×4 · @ 1.2345", al
        assert al["subtitle"] == "optimal · 100 $" and pl["aps"]["thread-id"] == "sub_1" and pl["trade_id"] == 7
        r2 = PUSH.payload_for({"kind": "rung", "mode": "dry", "sym": "AUSDT", "side": "long", "margin_usd": 6.25,
                               "px": 0.9, "avg": 0.95, "depth": "2/4"})
        assert r2["aps"]["alert"]["title"] == "Averaging [dry] · A long"
        assert r2["aps"]["alert"]["body"] == "6.25 $ · @ 0.9 · avg 0.95 · rung 2/4"
        r3 = PUSH.payload_for({"kind": "take", "mode": "live", "sym": "BUSDT", "side": "short", "px": 2.0,
                               "pnl_usd": 3.21, "pnl_bp": 128.4})
        assert r3["aps"]["alert"]["body"] == "@ 2 · +3.21 $ · +128 bp", r3
        assert "subtitle" not in r3["aps"]["alert"]            # нет книги — нет поля, не пустая строка
        assert set(PUSH.PUSHED_KINDS) >= {"entry", "rung", "take", "floor", "term", "market", "cmd_close",
                                           "reject", "halt", "mismatch"}


def test_devices_trades_ingest_and_push_chain():
    """Журнал исполнителя → запись → пуш на устройства; повтор чтения не
    дублирует; мёртвый токен выключается; пробное событие идёт той же
    дорогой и помечено test; чужая роль не задаёт ключ."""
    import push as PUSH
    calls = []
    answer = {"code": 200, "text": ""}

    def runner(url, headers, body):
        calls.append((url, headers, json.loads(body)))
        return answer["code"], answer["text"]

    with tempfile.TemporaryDirectory() as tmp:
        root = os.path.join(tmp, "dca")
        app, _ = _app(tmp, out=tmp, exec_root=root, sender=SV.PUSH.Sender(tmp, runner=runner))
        acc = _login(app)
        # устройство
        st, r = app.add_device(acc, "ZZZ", "prod", "115")
        assert st == 400
        st, r = app.add_device(acc, "ab" * 32, "prod", "115")
        assert st == 200 and r["devices"] == 1
        st, r = app.add_device(acc, "AB" * 32, "prod", "116")           # тот же токен — обновление
        assert st == 200 and r["devices"] == 1
        st, d = app.list_devices(acc)
        assert d["devices"][0]["build"] == "116" and d["push"] == {"configured": False}
        # пуш без ключа — отказ словами
        st, r = app.push_test(acc)
        assert st == 409 and "APNs" in r["error"]
        # ключ задаёт только оператор
        priv, _pub = _ec_pem()
        uid = app.db.create_account("user")
        user = app.db.account(uid)
        st, r = app.push_config(user, "TEAM123456", "KEY1234567", priv)
        assert st == 403
        st, r = app.push_config(acc, "TEAM123456", "KEY1234567", priv)
        assert st == 200 and r["key_id"] == "KEY1234567"
        st, r = app.push_test(acc)
        assert st == 200 and r["sent"] == 1 and r["results"][0]["status"] == 200, r
        url, headers, body = calls[-1]
        assert url.endswith("/3/device/" + "ab" * 32) and url.startswith(PUSH.HOSTS["prod"])
        assert headers["apns-topic"] == "pl.mdsauto.algoth" and headers["authorization"].startswith("bearer ")
        assert body["aps"]["alert"]["title"] == "Test event [test]"
        # журнал подписки: ключ и подписка — как в приложении
        st, k = app.add_key(acc, "bybit", "ABCD1234KEY", SECRET)
        st, sub = app.add_subscription(acc, k["key_id"], "optimal_h", 1000)
        sid = sub["subscription_id"]
        os.makedirs(os.path.join(root, sid))
        lines = [
            {"seq": 1, "ts": 1_791_000_000.0, "ev": "entry", "mode": "dry", "sym": "KAITOUSDT", "side": "short",
             "qty": 80.0, "px": 1.25, "margin_usd": 25.0, "lev": 4.0},
            "{битая строка",
            {"seq": 2, "ts": 1_791_000_600.0, "ev": "take_set", "mode": "dry", "sym": "KAITOUSDT", "side": "short",
             "px": 1.20},
            {"seq": 3, "ts": 1_791_003_600.0, "ev": "take", "mode": "dry", "sym": "KAITOUSDT", "side": "short",
             "px": 1.20, "pnl_usd": 3.9, "pnl_bp": 390.0},
        ]
        with open(os.path.join(root, sid, "events.jsonl"), "w", encoding="utf-8") as f:
            for ln in lines:
                f.write((ln if isinstance(ln, str) else json.dumps(ln)) + "\n")
        n0 = len(calls)
        assert app.push_tick() == 3
        assert len(calls) - n0 == 3                                   # пуш на КАЖДОЕ действие
        assert app.push_tick() == 0 and len(calls) - n0 == 3          # повтор чтения — ничего
        # по умолчанию — только живые: сухие скрыты и сосчитаны
        st, tr0 = app.list_trades(acc)
        assert st == 200 and tr0["trades"] == [] and tr0["hidden"] == 3 and "скрыто 3" in tr0["note"], tr0
        st, tr = app.list_trades(acc, mode="all")
        assert st == 200 and [t["seq"] for t in tr["trades"]] == [3, 2, 1] and tr["by_mode"] == {"dry": 3}
        t3 = tr["trades"][0]
        assert t3["kind"] == "take" and t3["words"] == "Closed at target" and t3["pnl_usd"] == 3.9
        assert t3["pushed"]["sent"] == 1 and t3["pushed"]["results"][0]["env"] == "prod"
        # лента по since — только новое
        st, tr2 = app.list_trades(acc, since=tr["trades"][-1]["id"], mode="all")
        assert [t["seq"] for t in tr2["trades"]] == [3, 2]
        # дописанная строка — новая запись; битые строки не роняют приём
        with open(os.path.join(root, sid, "events-2026-10-10.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps({"seq": 4, "ts": 1_791_010_000.0, "ev": "reject", "mode": "dry", "sym": "BUSDT",
                                "side": "short", "reason": "price cap 30 bp"}) + "\n")
        assert app.push_tick() == 1
        assert calls[-1][2]["aps"]["alert"]["body"] == "price cap 30 bp"
        # мёртвый токен: Apple отвечает 410 — устройство гаснет, следующий пуш его не ждёт
        answer.update(code=410, text=json.dumps({"reason": "Unregistered"}))
        st, r = app.push_test(acc)
        assert st == 200 and r["sent"] == 0 and r["results"][0]["dead"] is True
        st, d = app.list_devices(acc)
        assert d["devices"][0]["status"] == "dead" and d["devices"][0]["last_error"] == "Unregistered"
        answer.update(code=200, text="")
        st, r = app.push_test(acc)
        assert st == 409 and "нет зарегистрированных устройств" in r["error"]
        # пробное событие: только оператор; идёт через журнал, помечено test
        st, r = app.trade_test(user)
        assert st == 403
        app.add_device(acc, "cd" * 32, "sandbox", "116")
        st, r = app.trade_test(acc, "hello")
        assert st == 200 and r["ingested"] == 1 and r["trade"]["mode"] == "test" and r["trade"]["kind"] == "test"
        assert r["trade"]["reason"] == "hello" and r["trade"]["pushed"]["sent"] == 1
        assert calls[-1][0].startswith(PUSH.HOSTS["sandbox"])
        st, tr = app.list_trades(acc, mode="all")
        assert tr["by_mode"] == {"dry": 4, "test": 1} and tr["executor_running"] == "dry"
        assert [t["mode"] for t in app.list_trades(acc, mode="test")[1]["trades"]] == ["test"]
        assert SECRET not in json.dumps(tr)


def _pos(sym, at, fills, side="long", closed=None, lev=4.0, margin=25.0):
    walk, cash, qty = [], 0.0, 0.0
    for ts, px, w in fills:
        dq = w * margin * lev / px
        cash += w * margin * lev; qty += dq
        avg = cash / qty
        walk.append({"at": ts, "px": px, "w": w, "avg": avg, "dq": dq, "qty": qty,
                     "take": avg * (1.1 if side == "long" else 0.9)})
    p = {"sym": sym, "at": at, "side": side, "lev": lev, "margin": margin, "fills": [list(f) for f in fills],
         "walk": walk, "entry_px": fills[0][1], "avg": walk[-1]["avg"], "depth": len(fills),
         "sched_end": at + 72 * 3600, "state": "open"}
    if closed:
        p.update({"exit": closed, "exit_ts": at + 7200, "exit_px": walk[-1]["avg"] * 1.1,
                  "usd": 2.5, "pnl_frac": 0.1, "state": "closed", "tail": False})
    return p


def test_follower_turns_cell_positions_into_executor_events_once():
    """Сухой исполнитель: позиции ячейки подписки → события §7.6 — первый
    рунг вход, следующие доливы с переездом цели, исход по виду; позиции
    до подписки не ведутся; повторное чтение свода не дублирует; закрытие
    ранее открытой даёт только событие исхода. Контроль: без состояния
    слежения те же события отдаются второй раз."""
    import follow as F
    since = 1_791_000_000.0
    older = _pos("OLDUSDT", since - 10, [(since - 10, 1.0, 0.25)], closed="тейк")
    opened = _pos("AUSDT", since + 60, [(since + 60, 2.0, 0.25), (since + 600, 1.8, 0.25)])
    done = _pos("BUSDT", since + 120, [(since + 120, 5.0, 0.25)], side="short", closed="рынок")
    book = {"open": {"positions": [opened]}, "trades": [done, older], "trades_total": 2}
    evs, fl = F.plan(book, {}, since)
    kinds = [(e["ev"], e["sym"]) for e in evs]
    # по времени решения: входы, долив с переездом цели, потом исход
    assert kinds == [("entry", "AUSDT"), ("entry", "BUSDT"), ("rung", "AUSDT"), ("take_set", "AUSDT"), ("market", "BUSDT")], kinds
    e0 = evs[0]
    assert e0["depth"] == "1/2" and e0["qty"] == 0.25 * 25 * 4 / 2.0 and e0["term_ts"] == since + 60 + 72 * 3600
    assert e0["paper_margin_usd"] == 25.0 and e0["mode"] == "dry" and e0["take_px"] == 2.0 * 1.1
    assert e0["pos_at"] == since + 60 and evs[4]["pos_at"] == since + 120 and evs[4]["exit_ts_pos"] == done["exit_ts"]
    rung = evs[2]
    assert rung["depth"] == "2/2" and abs(rung["avg"] - (50 / (25 / 2.0 + 25 / 1.8))) < 1e-9 and rung["px"] == 1.8
    mk = evs[4]
    assert mk["pnl_usd"] == 2.5 and mk["pnl_bp"] == 250.0 and mk["px"] == done["exit_px"] and mk["ts"] == done["exit_ts"]
    assert "OLDUSDT" not in {e["sym"] for e in evs}, "позиция до подписки не ведётся"
    # повтор — ничего нового
    evs2, fl2 = F.plan(book, {"follow": fl}, since)
    assert evs2 == [], evs2
    # открытая закрылась по полу — только исход
    closed_a = dict(opened, exit="пол", exit_ts=since + 9000, exit_px=1.7, usd=-3.0, pnl_frac=-0.12, state="closed")
    book2 = {"open": {"positions": []}, "trades": [closed_a, done, older], "trades_total": 3}
    evs3, fl3 = F.plan(book2, {"follow": fl2}, since)
    assert [(e["ev"], e["sym"]) for e in evs3] == [("floor", "AUSDT")] and evs3[0]["pnl_bp"] == -300.0, evs3
    # контроль: без состояния — всё заново (дедуп держится состоянием, не журналом)
    evs4, _ = F.plan(book2, {}, since)
    assert len(evs4) == 6, len(evs4)
    # запись с растущим seq
    with tempfile.TemporaryDirectory() as root:
        assert F.append_events(root, "sub_x", evs) == 5
        assert F.append_events(root, "sub_x", evs3) == 1
        seqs = [json.loads(l)["seq"] for l in open(os.path.join(root, "sub_x", "events.jsonl"))]
        assert seqs == [1, 2, 3, 4, 5, 6], seqs


def test_follower_tick_feeds_trades_and_pushes_for_the_subscribed_cell():
    """Такт сервера: следователь → журнал подписки → записи `trades` с
    mode dry → пуш на устройство; чужие ячейки не трогаются."""
    calls = []

    def runner(url, headers, body):
        calls.append(json.loads(body)); return 200, ""
    since = 1_791_000_000.0
    pos = _pos("KAITOUSDT", since + 3600, [(since + 3600, 1.25, 0.25)], side="short", lev=4.0)
    dca = dict(DCA)
    dca["books"] = dict(DCA["books"])
    dca["books"]["optimal_h:1000"] = {"all": {"usd": 123.4, "final": 0.12, "n": 50},
                                      "open": {"positions": [pos]}, "trades": [], "trades_total": 0}
    dca["books"]["pair_optimal:1000"] = {"all": {"usd": -20.0}, "open": {"positions": [pos]}, "trades": []}
    with tempfile.TemporaryDirectory() as tmp:
        root = os.path.join(tmp, "dca")
        app, _ = _app(tmp, out=tmp, exec_root=root, sender=SV.PUSH.Sender(tmp, runner=runner),
                      dca_fetch=lambda full=None: dca)
        acc = _login(app)
        priv, _pub = _ec_pem()
        app.push_config(acc, "TEAM123456", "KEY1234567", priv)
        app.add_device(acc, "ab" * 32, "prod", "117")
        st, k = app.add_key(acc, "bybit", "ABCD1234KEY", SECRET)
        st, sub = app.add_subscription(acc, k["key_id"], "optimal_h", 1000)
        # подписка создана «сейчас», позиция — в будущем относительно неё
        app.db.c.execute("UPDATE subscriptions SET created=? WHERE id=?", (since, sub["subscription_id"]))
        assert app.push_tick() == 1
        st, tr = app.list_trades(acc, mode="all")
        t = tr["trades"][0]
        assert t["kind"] == "entry" and t["mode"] == "dry" and t["sym"] == "KAITOUSDT" and t["side"] == "short"
        assert t["subscription_id"] == sub["subscription_id"] and t["pushed"]["sent"] == 1
        assert calls[-1]["aps"]["alert"]["title"] == "Entry [dry] · KAITO short", calls[-1]
        assert tr["executor_running"] == "dry" and tr["by_mode"] == {"dry": 1}
        # состояние подписки несёт открытые позиции ячейки с уровнями и флагом слежения
        st, stt = app.state(acc)
        ps = stt["subscriptions"][0]["positions"]
        assert len(ps) == 1 and ps[0]["sym"] == "KAITOUSDT" and ps[0]["followed"] is True
        assert ps[0]["qty"] == pos["walk"][-1]["qty"] and ps[0]["take_px"] == pos["walk"][-1]["take"]
        assert ps[0]["term_ts"] == pos["sched_end"] and stt["subscriptions"][0]["follow"]["since"] == since
        assert app.push_tick() == 0                     # повтор такта — ничего
        stt = json.loads(app.db.subscription(sub["subscription_id"], acc["id"])["state_json"])
        assert stt["follow"]["seen"]["KAITOUSDT:%d" % (since + 3600)] == {"fills": 1, "closed": False}
        assert SECRET not in json.dumps(tr)



# ------------------------------------------------------------ намерения (L1)

def _flat_bars(t0, n=1440, px=100.0, jitter=0.0):
    out = []
    for i in range(n):
        d = jitter * ((i % 7) - 3) / 3.0
        out.append((t0 + i * 60, px + d, px + d + 0.2, px + d - 0.2, px + d, 1000.0))
    return out


def _bars_fn(bars):
    def bars_of(sym, t0, t1):
        return [b for b in bars if t0 <= b[0] <= t1]
    return bars_of


def _sheet_line(hour, written_at, rows, arm="nn"):
    return json.dumps({"hour": hour, "written_at": written_at, "arms": {arm: rows}})


def _pick_line(hour, shorts, arm="nn"):
    return json.dumps({"arm": arm, "hour": hour, "long": [], "short": shorts})


def test_intents_plan_entry_like_paper_and_size_from_subscription_cash():
    """Намерение входа считается теми же функциями, что бумага: вход, плечо,
    рунги, цель, пол и ликвидация совпадают с записью `run_d6.one_position`
    того же решения на тех же барах; размер — доля кассы подписки (сложный
    процент: депозит + реализованное; фиксированный билет: депозит);
    короткая книга h24 — один рунг и плечо забора; отказы — одна на имя
    (бумага держит), гейт плеча агрессивной, нет кассы, возраст имени;
    незакрытый бар входа — ожидание, не отказ."""
    import intents as I
    c = I.core()
    R, D2, D6, L = c["R"], c["D2"], c["D6"], c["L"]
    t0 = 1_791_000_000 - 1_791_000_000 % 3600
    at = t0 + 1440 * 60                      # решение — конец 24-го часа
    bars = _flat_bars(t0, n=1440 + 5)        # пять баров после входа
    now = at + 4 * 60 + 5                    # xx:04:05 — бар входа закрыт
    LEVELS = [97.0, 94.0, 91.0, 88.0, 103.0, 106.0, 109.0]
    orig = D2.build_levels
    D2.build_levels = lambda w, i: LEVELS
    try:
        g_long = {"arm": "nn", "sym": "AAAUSDT", "hour": "x", "at": float(at), "side": "long",
                  "fwd": 120.0, "fz": 2.0, "adv_q": -300.0, "fav": 250.0, "rr": 250 / 300}
        g_short = {"arm": "nn", "sym": "BBBUSDT", "hour": "x", "at": float(at), "side": "short",
                   "fwd": -120.0, "fz": None, "adv_q": 300.0, "fav": -250.0, "rr": 250 / 300}
        ts = [b[0] for b in bars]
        look = lambda notl: L.mmr_for_notional([], notl, flat=D2.FLAT_MMR)      # noqa: E731
        sub = {"id": "sub_t", "book": "optimal", "deposit": 1000.0, "created": at - 10}
        st = {"sizing": "compound", "realized_usd": 200.0}
        env = {"now": now, "bars": _bars_fn(bars), "launch": {}, "tiers": {}}
        ints, skips, it = I.decide(sub, st, {"sit": [g_long]}, None, env, log=lambda *a: None)
        assert len(ints) == 1 and not skips, (ints, skips)
        r = ints[0]
        # то же, что посчитает бумага на тех же барах
        rec = D6.one_position(g_long, bars, ts, look, "depth", R.SURVIVE_MULT, hold_h=72)
        assert r["px_ref"] == rec["entry_px"] == 100.0 and r["lev"] == rec["lev"] and r["lev"] > 1.0, (r["lev"], rec["lev"])
        assert [x["px"] for x in r["rungs"]] == [100.0, 97.0, 94.0, 91.0] and [x["share"] for x in r["rungs"]] == [0.25] * 4
        share = R.share(1000.0, "optimal")
        assert abs(r["margin_usd"] - 1200.0 * share) < 1e-6 and r["cash_usd"] == 1200.0, r
        paper_lv = R.levels_of(dict(rec, margin=r["margin_usd"]), "optimal", look=look)
        assert abs(r["take_px"] - paper_lv["take_px"]) < 1e-9 and abs(r["floor_px"] - paper_lv["floor_px"]) < 1e-9
        assert abs(r["liq_px"] - paper_lv["liq_px"]) < 1e-9 and r["term_ts"] == at + 72 * 3600 and r["side"] == "long"
        assert r["take_px"] == 100.0 * (1 + 2 * 250 / 1e4) and r["floor_px"] < 100.0 and r["liq_px"] < r["floor_px"]
        assert it["live"][I.leg_key("optimal", g_long)]["margin_usd"] == r["margin_usd"] and r["mode"] == "dry"
        # фиксированный билет — от депозита, не от кассы
        ints_f, _s, _i = I.decide(sub, dict(st, sizing="fixed"), {"sit": [g_long]}, None, env, log=lambda *a: None)
        assert abs(ints_f[0]["margin_usd"] - 1000.0 * share) < 1e-6 and ints_f[0]["cash_usd"] == 1000.0
        # короткая книга h24: один рунг, плечо забора на структурной лестнице, цель ниже, пол выше
        sub_h = {"id": "sub_h", "book": "optimal_h", "deposit": 1000.0, "created": at - 10}
        env_h = dict(env, launch={"BBBUSDT": at - 30 * 86400})
        ints_h, skips_h, it_h = I.decide(sub_h, {"sizing": "compound"}, {"h24": [g_short]}, None, env_h, log=lambda *a: None)
        assert len(ints_h) == 1 and not skips_h, (ints_h, skips_h)
        h = ints_h[0]
        assert h["side"] == "short" and [x["px"] for x in h["rungs"]] == [100.0] and h["rungs"][0]["share"] == 0.25
        assert h["rungs_full"] == [100.0, 103.0, 106.0, 109.0] and h["lev"] > 1.0 and h["hold_h"] == 24
        assert h["take_px"] == 100.0 * (1 - 2 * 250 / 1e4) and h["floor_px"] > 100.0 and h["liq_px"] > h["floor_px"]
        assert abs(h["margin_usd"] - 1000.0 * R.share_in("optimal_h", "optimal_h", 1000.0)) < 1e-9
        # общий счёт: короткая сторона своим билетом × доля, длинная своим
        sub_p = {"id": "sub_p", "book": "pair_optimal", "deposit": 10000.0, "created": at - 10}
        ints_p, skips_p, _ = I.decide(sub_p, {"sizing": "compound"}, {"sit": [g_long], "h24": [g_short]}, None,
                                      env_h, log=lambda *a: None)
        assert sorted((x["book"], x["sym"]) for x in ints_p) == [("optimal", "AAAUSDT"), ("optimal_h", "BBBUSDT")], ints_p
        by = {x["book"]: x for x in ints_p}
        assert abs(by["optimal_h"]["margin_usd"] - 10000.0 * R.share_in("pair_optimal", "optimal_h", 10000.0)) < 1e-9
        assert abs(by["optimal"]["margin_usd"] - 10000.0 * R.share_in("pair_optimal", "optimal", 10000.0)) < 1e-9
        # отказы: возраст имени (молодое / неизвестное), одна на имя, гейт плеча, нет кассы
        _i1, sk1, _ = I.decide(sub_h, {}, {"h24": [g_short]}, None, dict(env, launch={"BBBUSDT": at - 86400}), log=lambda *a: None)
        assert len(sk1) == 1 and "возраст" in sk1[0]["why"], sk1
        _i2, sk2, _ = I.decide(sub_h, {}, {"h24": [g_short]}, None, dict(env, launch={"OTHER": at - 86400}), log=lambda *a: None)
        assert len(sk2) == 1 and "возраст" in sk2[0]["why"], sk2
        book_cell = {"open": {"positions": [{"sym": "AAAUSDT", "at": at - 7200, "book": None}]}}
        _i3, sk3, _ = I.decide(sub, st, {"sit": [g_long]}, book_cell, env, log=lambda *a: None)
        assert len(sk3) == 1 and sk3[0]["why"].startswith("одна позиция на имя: бумага"), sk3
        sub_a = {"id": "sub_a", "book": "aggr", "deposit": 1000.0, "created": at - 10}
        # глубокая лестница → забор даёт плечо 1.9 (ниже гейта 4); лестница
        # LEVELS → 6.3 (проходит): числа — от `fence_leverage`, не назначены
        D2.build_levels = lambda w, i: [90.0, 80.0, 70.0]
        _i4, sk4, _ = I.decide(sub_a, {}, {"sit": [g_long]}, None, env, log=lambda *a: None)
        assert len(sk4) == 1 and sk4[0]["why"].startswith("гейт плеча: 1.8"), sk4
        D2.build_levels = lambda w, i: LEVELS
        i5, sk5, _ = I.decide(sub_a, {}, {"sit": [g_long]}, None, env, log=lambda *a: None)
        assert len(i5) == 1 and i5[0]["lev"] >= R.AGGR_MIN_LEV, (i5, sk5)
        full = {"intents": {"live": {f"optimal:X{i}USDT:{at}": {"sym": f"X{i}USDT", "book": "optimal",
                                                                "margin_usd": 300.0, "term_ts": at + 3600}
                                     for i in range(4)}}}
        _i6, sk6, _ = I.decide(sub, dict(st, **full), {"sit": [g_long]}, None, env, log=lambda *a: None)
        assert len(sk6) == 1 and sk6[0]["why"].startswith("нет кассы"), sk6
        # решение, увиденное впервые через 20+ мин после себя, — отказ «поздно», не вход задним числом
        _il, skl, _ = I.decide(sub, st, {"sit": [g_long]}, None, dict(env, now=at + I.PENDING_MAX_S + 60), log=lambda *a: None)
        assert not _il and len(skl) == 1 and skl[0]["why"].startswith("решение пришло поздно: возраст 21 мин"), skl
        # …но решение, ДОСТУПНОЕ нам минуту (прошлое чтение источника минуту назад), свежее при любой метке часа:
        # цикл пишет выборы часа с опозданием — это отставание едет числом, не отказом
        il2, skl2, _ = I.decide(sub, st, {"sit": [g_long]}, None,
                                dict(env, now=at + I.PENDING_MAX_S + 60, avail_age={"sit": 60.0}), log=lambda *a: None)
        assert len(il2) == 1 and not skl2 and il2[0]["lag_s"] == I.PENDING_MAX_S + 60, (il2, skl2)
        il3, skl3, _ = I.decide(sub, st, {"sit": [g_long]}, None,
                                dict(env, now=at + I.PENDING_MAX_S + 60, avail_age={"sit": I.PENDING_MAX_S + 1}), log=lambda *a: None)
        assert not il3 and len(skl3) == 1, "доступно дольше предела и метка стара — поздно"
        # решение до подписки не ведётся; повтор того же решения не дублируется
        _i7, sk7, it7 = I.decide(dict(sub, created=at + 1), {}, {"sit": [g_long]}, None, env, log=lambda *a: None)
        assert not _i7 and not sk7
        _i8, sk8, _ = I.decide(sub, dict(st, intents=it), {"sit": [g_long]}, None, env, log=lambda *a: None)
        assert not _i8 and not sk8, (_i8, sk8)
        # бар входа не закрыт — ждём; пришёл — намерение, тем же решением
        early = dict(env, now=at + 30, bars=_bars_fn([b for b in bars if b[0] <= at]))
        i9, sk9, it9 = I.decide(sub, st, {"sit": [g_long]}, None, early, log=lambda *a: None)
        assert not i9 and not sk9 and len(it9["pending"]) == 1 and "бар" in it9["pending"][0]["why"], it9
        i10, sk10, it10 = I.decide(sub, dict(st, intents=it9), {}, None, env, log=lambda *a: None)
        assert len(i10) == 1 and i10[0]["px_ref"] == 100.0 and not it10["pending"], (i10, it10)
        # контроль: бар так и не пришёл — отказ с причиной, не вечное ожидание
        late = dict(early, now=at + I.PENDING_MAX_S + 1)
        i11, sk11, it11 = I.decide(sub, dict(st, intents=it9), {}, None, late, log=lambda *a: None)
        assert not i11 and len(sk11) == 1 and "не пришёл" in sk11[0]["why"] and not it11["pending"], sk11
    finally:
        D2.build_levels = orig
    print("ok  намерения: геометрия как у бумаги, размер от кассы подписки, отказы с причиной")


def test_intents_sources_are_read_as_tail_once_and_tick_feeds_state_and_parity():
    """Такт сервера: источники читаются хвостом от смещения (первое чтение —
    хвост, неполная строка остаётся), ноги собираются тем же правилом, что
    реплей; намерение пишется в intents.jsonl с seq, отказ — в skips.jsonl;
    состояние несёт сводку, /intents отдаёт хвост; сверка с бумагой находит
    строку того же решения и печатает Δ = 0, а строку бумаги без намерения
    называет причиной отказа."""
    import intents as I
    c = I.core()
    D2, R = c["D2"], c["R"]
    t0 = 1_791_000_000 - 1_791_000_000 % 3600
    at = t0 + 1440 * 60
    hour = time.strftime("%Y-%m-%d-%H", time.gmtime(at - 3600))
    bars = _flat_bars(t0, n=1440 + 6)
    now = at + 5 * 60
    orig = D2.build_levels
    D2.build_levels = lambda w, i: [97.0, 94.0, 91.0, 103.0, 106.0]
    try:
        with tempfile.TemporaryDirectory() as tmp:
            picks = os.path.join(tmp, "picks.jsonl")
            sheets = os.path.join(tmp, "sheets.jsonl")
            # хвост источника: старая строка (до подписки) и новая; последняя — без перевода строки
            with open(picks, "w", encoding="utf-8") as f:
                f.write(_pick_line("2026-01-01-00", [{"sym": "OLDUSDT", "fwd": -400.0, "mae": 120.0, "mfe": -600.0, "px": 1.0}]) + "\n")
                f.write(_pick_line(hour, [{"sym": "BBBUSDT", "fwd": -400.0, "mae": 120.0, "mfe": -600.0, "px": 100.0},
                                          {"sym": "YNGUSDT", "fwd": -400.0, "mae": 120.0, "mfe": -600.0, "px": 100.0},
                                          {"sym": "LOWUSDT", "fwd": -20.0, "mae": 120.0, "mfe": -600.0, "px": 100.0}]) + "\n")
                f.write('{"arm": "nn", "hour": "2026-')                   # незаконченная запись
            lines, sst, why = I.read_tail(picks, {}, first_tail=10 ** 9)
            assert len(lines) == 2 and why is None and sst["offset"] == os.path.getsize(picks) - len('{"arm": "nn", "hour": "2026-'), sst
            lines2, sst2, _ = I.read_tail(picks, sst)
            assert lines2 == [] and sst2["offset"] == sst["offset"] and sst2["prev_at"] == sst["at"]
            with open(picks, "a", encoding="utf-8") as f:
                f.write('01-01"}\n')
            lines3, sst3, _ = I.read_tail(picks, sst2)
            assert len(lines3) == 1 and sst3["offset"] == os.path.getsize(picks)
            # первое чтение с хвоста режет неполную первую строку
            lines4, _s4, _ = I.read_tail(picks, {}, first_tail=40)
            assert lines4 == [] or all(json.loads(x) for x in lines4)
            legs = I.legs_from_lines("h24", lines, log=lambda *a: None)
            assert sorted(g["sym"] for g in legs) == ["BBBUSDT", "OLDUSDT", "YNGUSDT"], legs   # LOW — край < 33
            assert all(g["side"] == "short" and g["fav"] == -600.0 and g["adv_q"] == 120.0 for g in legs)
            with open(sheets, "w", encoding="utf-8") as f:
                f.write(_sheet_line(hour, at + 1.5, [{"sym": "AAAUSDT", "fwd": 120.0, "px": 100.0, "mae": -100.0, "mfe": 250.0},
                                                      {"sym": "RRRUSDT", "fwd": 120.0, "px": 100.0, "mae": -300.0, "mfe": 250.0}]) + "\n")
            sl = I.legs_from_lines("sit", [open(sheets).read().strip()], log=lambda *a: None)
            assert [g["sym"] for g in sl] == ["AAAUSDT"] and sl[0]["at"] == at + 1.5, sl   # RRR — RR < 2
            # такт сервера с подменёнными источниками и барами
            root = os.path.join(tmp, "exec")
            dca = dict(DCA)
            dca["books"] = dict(DCA["books"])
            paper_row = {"sym": "BBBUSDT", "at": float(at), "side": "short", "entry_px": 100.0, "lev": None, "margin": None,
                         "fills": [[at, 100.0, 0.25]], "levels": None, "exit": "срок", "exit_ts": at + 86400}
            dca["books"]["optimal_h:1000"] = {"all": {"usd": 1.0}, "open": {"positions": []},
                                              "trades": [paper_row], "trades_total": 1}
            app, _ = _app(tmp, out=tmp, exec_root=root, dca_fetch=lambda full=None: dca)
            acc = _login(app)
            st, k = app.add_key(acc, "bybit", "ABCD1234KEY", SECRET)
            st, sub = app.add_subscription(acc, k["key_id"], "optimal_h", 1000)
            app.db.c.execute("UPDATE subscriptions SET created=? WHERE id=?", (at - 10, sub["subscription_id"]))
            app.intents_env = {"now": now, "bars": _bars_fn(bars), "tiers": {},
                               "launch": {"BBBUSDT": at - 30 * 86400, "YNGUSDT": at - 2 * 86400, "OLDUSDT": at - 90 * 86400},
                               "files": {"h24": picks, "sit": sheets}}
            n = app.intents_tick(force=True)
            assert n == 1, n
            rows = I.read_rows(I.intents_path(root, sub["subscription_id"]))
            assert len(rows) == 1 and rows[0]["seq"] == 1 and rows[0]["sym"] == "BBBUSDT" and rows[0]["cell"] == "optimal_h"
            assert rows[0]["decided_at"] == at and rows[0]["px_ref"] == 100.0 and rows[0]["lev"] > 1
            sk = I.read_rows(I.skips_path(root, sub["subscription_id"]))
            assert [x["sym"] for x in sk] == ["YNGUSDT"] and "возраст" in sk[0]["why"], sk
            # бумажная строка дополнена плечом и маржой намерения — сверка даёт нули
            paper_row["lev"], paper_row["margin"] = rows[0]["lev"], rows[0]["margin_usd"]
            paper_row["levels"] = {"take_px": rows[0]["take_px"], "floor_px": rows[0]["floor_px"]}
            dca["books"]["optimal_h:1000"]["trades"].append(
                {"sym": "YNGUSDT", "at": float(at), "side": "short", "entry_px": 100.0, "lev": 3.0, "margin": 25.0})
            app._dca["at"] = 0.0
            n2 = app.intents_tick(force=True)
            assert n2 == 0
            st_, stt = app.state(acc)
            summ = stt["subscriptions"][0]["intents"]
            assert summ["n"] == 1 and summ["n_skips"] == 1 and summ["live"] == 1 and summ["error"] is None, summ
            assert set(summ["source_age_s"]) == {"h24"} and summ["source_age_s"]["h24"] is not None, summ
            p = summ["parity"]
            assert p["intents"] == 1 and p["matched"] == 1 and p["paper_only"] == 1 and p["intent_only"] == 0, p
            assert p["fields"]["entry_bp"] == {"n": 1, "median": 0.0, "max": 0.0} and p["fields"]["lev_d"]["max"] == 0.0
            assert p["fields"]["take_bp"]["max"] == 0.0 and p["fields"]["floor_bp"]["max"] == 0.0 and p["fields"]["margin_d"]["max"] == 0.0
            assert p["paper_only_tail"][0]["sym"] == "YNGUSDT" and "возраст" in p["paper_only_tail"][0]["why"], p
            # смещение источника запомнено: повторный такт ничего не перечитывает
            sst_saved = I.load_sources_state(root)
            assert sst_saved[picks]["offset"] == os.path.getsize(picks) and sst_saved[picks]["read"] >= 3
            st_, li = app.list_intents(acc)
            assert li["subscriptions"][0]["intents"][0]["sym"] == "BBBUSDT" and li["subscriptions"][0]["skips"][0]["sym"] == "YNGUSDT"
            assert li["subscriptions"][0]["summary"]["parity"]["matched"] == 1
            # контроль: без состояния источников хвост читается заново — и дедуп держит состояние подписки
            os.remove(I.sources_state_path(root))
            assert app.intents_tick(force=True) == 0
            assert len(I.read_rows(I.intents_path(root, sub["subscription_id"]))) == 1
            # следующий час: новое решение по тому же имени — одна на имя (намерение держит)
            hour2 = time.strftime("%Y-%m-%d-%H", time.gmtime(at))
            with open(picks, "a", encoding="utf-8") as f:
                f.write(_pick_line(hour2, [{"sym": "BBBUSDT", "fwd": -400.0, "mae": 120.0, "mfe": -600.0, "px": 100.0}]) + "\n")
            bars2 = bars + _flat_bars(at + 6 * 60, n=3600, px=100.0)
            app.intents_env.update({"now": at + 3600 + 5 * 60, "bars": _bars_fn(bars2)})
            assert app.intents_tick(force=True) == 0
            sk2 = I.read_rows(I.skips_path(root, sub["subscription_id"]))
            assert sk2[-1]["sym"] == "BBBUSDT" and "намерение держит" in sk2[-1]["why"], sk2[-1]
            assert SECRET not in json.dumps(li)
            # сброс подписки: файлы переименованы (не удалены), состояние чисто, смещения источников целы
            r = I.reset_sub(app.db, root, sub["subscription_id"], now=at)
            assert r["had_intents"] == 1 and r["had_live"] == 1 and len(r["moved"]) == 2, r
            d = os.path.join(root, sub["subscription_id"])
            assert not os.path.exists(I.intents_path(root, sub["subscription_id"])) and any("intents-stale-" in x for x in os.listdir(d))
            assert "intents" not in json.loads(app.db.subscription(sub["subscription_id"], acc["id"])["state_json"])
            assert I.load_sources_state(root)[picks]["offset"] == os.path.getsize(picks)
            assert I.reset_sub(app.db, root, "sub_nope")["error"].startswith("подписки")
    finally:
        D2.build_levels = orig
    print("ok  такт намерений: хвост источников, файлы с seq, сводка в состоянии, сверка с бумагой, сброс")



def test_intents_for_live_sub_use_executor_cash_names_levels_and_guard_exits():
    """Живая подписка: уровни на КАЖДОЙ глубине — `levels_of` по плановым
    ценам рунгов; касса — депозит + реализованное исполнителем; имена и
    деньги держат позиции исполнителя (односторонний счёт: любое имя
    исполнителя занято для обеих сторон); намерение, прочитанное
    исполнителем, денег не держит; охрана рынком даёт выход один раз."""
    import intents as I
    c = I.core()
    R, D2, L = c["R"], c["D2"], c["L"]
    t0 = 1_791_000_000 - 1_791_000_000 % 3600
    at = t0 + 1440 * 60
    bars = _flat_bars(t0, n=1440 + 5)
    now = at + 4 * 60 + 5
    orig = D2.build_levels
    D2.build_levels = lambda w, i: [97.0, 94.0, 91.0, 103.0]
    try:
        g = {"arm": "nn", "sym": "AAAUSDT", "hour": "x", "at": float(at), "side": "long",
             "fwd": 120.0, "fz": 2.0, "adv_q": -300.0, "fav": 250.0, "rr": 2.5}
        sub = {"id": "sub_l", "book": "optimal", "deposit": 1000.0, "created": at - 10, "mode": "live"}
        env = {"now": now, "bars": _bars_fn(bars), "launch": {}, "tiers": {}}
        ints, _sk, it = I.decide(sub, {"sizing": "compound"}, {"sit": [g]}, None, env, log=lambda *a: None)
        r = ints[0]
        look = lambda notl: L.mmr_for_notional([], notl, flat=D2.FLAT_MMR)      # noqa: E731
        assert [x["px"] for x in r["rungs"]] == [100.0, 97.0, 94.0, 91.0]
        for k in range(1, 5):
            row = {"sym": "AAAUSDT", "side": "long", "entry_px": 100.0, "margin": r["margin_usd"], "lev": r["lev"],
                   "fav_bp": 250.0, "sched_end": r["term_ts"],
                   "fills": [[r["entry_ts"], x["px"], x["share"]] for x in r["rungs"][:k]]}
            lv = R.levels_of(row, "optimal", look=look)
            got = r["rungs"][k - 1]
            assert abs(got["floor_px"] - lv["floor_px"]) < 1e-9 and abs(got["avg"] - lv["avg"]) < 1e-9, (k, got, lv)
        floors = [x["floor_px"] for x in r["rungs"]]
        assert floors == sorted(floors), "у лонга пол поднимается с глубиной (средняя ниже, ликвидация выше)"
        assert r["notional_full_usd"] == round(r["margin_usd"] * r["lev"], 4)
        # исполнитель держит AAAUSDT шортом другой книги — лонг того же имени не входит
        ex = {"seq_done": 3, "realized_usd": 50.0, "positions": [
            {"sym": "AAAUSDT", "side": "short", "book": "optimal_h", "pos_at": at - 3600, "margin_usd": 25.0,
             "term_ts": at + 3600}]}
        _i, sk, _ = I.decide(sub, {"sizing": "compound"}, {"sit": [g]}, None, dict(env, exec=ex), log=lambda *a: None)
        assert not _i and sk[0]["why"] == "одна позиция на имя: исполнитель держит (односторонний счёт)", sk
        # касса = депозит + реализованное исполнителем; маржа исполнителя занята
        g2 = dict(g, sym="BBBUSDT")
        i2, _s, it2 = I.decide(sub, {"sizing": "compound"}, {"sit": [g2]}, None, dict(env, exec=ex), log=lambda *a: None)
        assert i2[0]["cash_usd"] == 1050.0 and abs(i2[0]["margin_usd"] - 1050.0 * R.share(1000.0, "optimal")) < 1e-9
        assert any(v.get("exec") for v in it2["live"].values())
        # намерение, прочитанное исполнителем (seq ≤ seq_done), денег не держит
        st_live = {"sizing": "compound", "intents": {"live": {
            "optimal:CCCUSDT:1": {"sym": "CCCUSDT", "book": "optimal", "margin_usd": 1000.0, "term_ts": now + 999, "seq": 2},
            "optimal:DDDUSDT:1": {"sym": "DDDUSDT", "book": "optimal", "margin_usd": 1040.0, "term_ts": now + 999, "seq": 9}}}}
        _i3, sk3, it3 = I.decide(sub, st_live, {"sit": [dict(g, sym="EEEUSDT")]}, None, dict(env, exec=dict(ex, positions=[])),
                                 log=lambda *a: None)
        assert "optimal:CCCUSDT:1" not in it3["live"] and "optimal:DDDUSDT:1" in it3["live"]
        assert sk3 and sk3[0]["why"].startswith("нет кассы"), "непрочитанное намерение на 1040 $ держит кассу 1050 $"
    finally:
        D2.build_levels = orig

    class Mkt:
        def __init__(self):
            self.calls = []

        def k_star(self, at, pct, kmax):
            self.calls.append((at, pct, kmax))
            return (3, 0) if at == 100.0 else (None, 0)
    mkt = Mkt()
    ex = {"positions": [{"sym": "SSSUSDT", "side": "short", "book": "aggr_h", "pos_at": 100.0},
                        {"sym": "TTTUSDT", "side": "short", "book": "aggr_h", "pos_at": 200.0},
                        {"sym": "LLLUSDT", "side": "long", "book": "aggr", "pos_at": 100.0}]}
    it = {}
    out = I.guard_exits({"id": "s"}, ex, it, {"market": mkt, "now": 1000.0})
    assert [(o["kind"], o["sym"], o["reason"], o["wave_k"]) for o in out] == [("exit", "SSSUSDT", "market", 3)], out
    assert mkt.calls[0] == (100.0, R.wave_guard_of("aggr_h"), R.H24_HOLD_H - 1)
    assert len(mkt.calls) == 2, "длинная книга охраны не имеет"
    assert I.guard_exits({"id": "s"}, ex, it, {"market": mkt, "now": 1001.0}) == [], "выход пишется один раз"
    print("ok  намерения живой подписки: уровни по глубинам, касса и имена исполнителя, охрана рынком")


# ------------------------------------------------------------ живой режим (L3)

def test_arm_needs_word_switch_fresh_equity_and_one_live_per_key():
    """Перевод в живые сделки — только кнопкой владельца с подтверждением
    словом `книга:депозит`; рубильник оператора, свежее эквити не ниже
    кассы и одна живая подписка на ключ проверяются машиной, отказ —
    словами. После перевода: входы выключаются файлом (позиции ведутся),
    KILL — файлом, обратно в сухой — только без позиций; следователь
    живую подписку не ведёт; состояние берёт позиции у исполнителя."""
    with tempfile.TemporaryDirectory() as tmp:
        root = os.path.join(tmp, "exec")
        app, _ = _app(tmp, out=tmp, exec_root=root)
        acc = _login(app)
        st, k = app.add_key(acc, "bybit", "ABCD1234KEY", SECRET)
        st, sub = app.add_subscription(acc, k["key_id"], "optimal_h", 1000)
        sid = sub["subscription_id"]
        code, r = app.arm(acc, sid, "optimal_h:100")
        assert code == 400 and "optimal_h:1000" in r["error"], r
        code, r = app.arm(acc, sid, "optimal_h:1000")
        assert code == 409 and "рубильник" in r["error"], r
        assert app.set_live_enabled(acc, True)[1]["live_enabled"] is True
        # эквити от добавления ключа (1500) свежее суток и не ниже кассы 1000
        code, r = app.arm(acc, sid, "optimal_h:1000")
        assert code == 200 and r["mode"] == "live", r
        row = app.db.subscription(sid, acc["id"])
        assert row["mode"] == "live" and row["armed_by"] == acc["id"]
        # вторая подписка на тот же ключ — отказ
        st, sub2 = app.add_subscription(acc, k["key_id"], "pair_optimal", 1000)
        code, r = app.arm(acc, sub2["subscription_id"], "pair_optimal:1000")
        assert code == 409 and "уже есть живая подписка" in r["error"], r
        # эквити протухло или ниже кассы — отказ
        app.db.c.execute("UPDATE subscriptions SET mode='dry' WHERE id=?", (sid,))
        app.db.c.execute("UPDATE exchange_keys SET equity_at=? WHERE id=?", (time.time() - 2 * 86400, k["key_id"]))
        assert "не измерено за сутки" in app.arm(acc, sid, "optimal_h:1000")[1]["error"]
        app.db.set_equity(k["key_id"], 900.0)
        assert "касса подписки 1,000.00" in app.arm(acc, sid, "optimal_h:1000")[1]["error"]
        app.db.set_equity(k["key_id"], 1500.0)
        assert app.arm(acc, sid, "optimal_h:1000")[0] == 200
        # входы выключены файлом, повторный arm их включает
        assert app.disarm(acc, sid)[0] == 200 and os.path.exists(os.path.join(root, sid, "NO_ENTRIES"))
        assert app.arm(acc, sid, "optimal_h:1000")[0] == 200 and not os.path.exists(os.path.join(root, sid, "NO_ENTRIES"))
        # KILL — файлом, только оператору
        assert app.kill(acc, sid, True)[1]["kill"] and os.path.exists(os.path.join(root, sid, "KILL"))
        assert app.kill(acc, sid, False)[0] == 200 and not os.path.exists(os.path.join(root, sid, "KILL"))
        # состояние: исполнитель ещё не поднят — сказано словами
        stt = app.state(acc)[1]["subscriptions"][0]
        assert stt["mode"] == "live" and stt["executor"]["why_none"].startswith("исполнитель ещё не поднят"), stt["executor"]
        assert stt["positions"] == [], "у живой подписки без исполнителя позиций бумаги нет"
        # живая запись исполнителя — на вкладке по умолчанию, пробная — нет
        os.makedirs(os.path.join(root, sid), exist_ok=True)
        with open(os.path.join(root, sid, "events.jsonl"), "w") as f:
            f.write(json.dumps({"seq": 1, "ts": time.time(), "ev": "entry", "mode": "live", "sym": "XUSDT",
                                "side": "short", "qty": 5.0, "px": 2.0}) + "\n")
        import tradelog as TL
        TL.ingest(app.db, root, log=lambda *a: None)
        tr = app.list_trades(acc)[1]
        assert [t["mode"] for t in tr["trades"]] == ["live"] and tr["executor_running"] == "live", tr
        # исполнитель поднят: позиции и касса — его
        with open(os.path.join(root, sid, "ladder_status.json"), "w") as f:
            json.dump({"at_ms": time.time() * 1000, "mode": "live", "realized_usd": -3.5, "positions": [
                {"sym": "XUSDT", "side": "short", "pos_at": 1.0, "avg": 2.0, "qty": 5.0, "lev": 4.0,
                 "margin_usd": 25.0, "depth": "1/1", "take_px": 1.8, "floor_px": 2.1, "term_ts": 9.0}]}, f)
        stt = app.state(acc)[1]["subscriptions"][0]
        assert stt["cash_usd"] == 996.5 and stt["positions"][0]["sym"] == "XUSDT" and stt["positions"][0]["live"]
        assert stt["executor"]["status"]["realized_usd"] == -3.5 and stt["executor"]["age_s"] < 60
        # обратно в сухой — только без позиций
        code, r = app.to_dry(acc, sid)
        assert code == 409 and "открыто позиций 1" in r["error"], r
        os.remove(os.path.join(root, sid, "ladder_status.json"))
        assert app.to_dry(acc, sid)[0] == 200
        # следователь живую подписку не ведёт
        import follow as F
        app.db.c.execute("UPDATE subscriptions SET mode='live' WHERE id=?", (sid,))
        rows = app.db.c.execute("SELECT * FROM subscriptions WHERE status='active' AND mode!='live'").fetchall()
        assert sid not in {r["id"] for r in rows}
        # проверка счёта — текст отдельного процесса, ключа в ответе нет
        fake = type("R", (), {"stdout": "ключ: открывается\nитог: годен\n", "stderr": ""})
        code, r = app.check_account(acc, sid, runner=lambda c: fake)
        assert code == 200 and r["ok"] and SECRET not in json.dumps(r)
    print("ok  живой режим: слово, рубильник, эквити, один на ключ, файлы входов и KILL, позиции исполнителя")


def test_live_positions_are_built_from_executor_journal_in_paper_row_shape():
    """Живые позиции — строками той же формы, что бумажные: вход и доливы
    из журнала исполнителя (`fills`, `walk` с контрактами, средней и целью
    после каждого), исход закрытой словом бумаги, отметка открытой из
    статуса исполнителя за вычетом комиссий; сухие и пробные записи в
    позиции не попадают."""
    with tempfile.TemporaryDirectory() as tmp:
        root = os.path.join(tmp, "exec")
        app, _ = _app(tmp, out=tmp, exec_root=root)
        acc = _login(app)
        st, k = app.add_key(acc, "bybit", "ABCD1234KEY", SECRET)
        st, sub = app.add_subscription(acc, k["key_id"], "optimal_h", 1000)
        sid = sub["subscription_id"]
        app.db.c.execute("UPDATE subscriptions SET mode='live' WHERE id=?", (sid,))
        d = os.path.join(root, sid)
        os.makedirs(d)
        T = 1_791_000_000.0
        # бумажная ячейка: та же короткая сделка (сырой журнал, своя маржа 42)
        # и та же длинная открытой; позиции позже последней строки бумаги нет
        dca = dict(DCA)
        dca["books"] = dict(DCA["books"])
        dca["books"]["optimal_h:1000"] = {"all": {"usd": 1.0}, "trades": [
            {"sym": "SUSDT", "at": T + 60, "side": "short", "entry_px": 2.02, "exit_px": 1.81, "exit": "тейк",
             "exit_ts": T + 900, "margin": 42.0, "usd": 4.2, "pnl_frac": 0.1}],
            "open": {"positions": [{"sym": "AUSDT", "at": T, "side": "long", "entry_px": 99.8, "margin": 42.0,
                                    "mark_usd": 2.1, "mark_frac": 0.05}]}}
        app.dca_fetch = lambda full=None: dca
        app._dca = {"at": 0.0, "data": None}
        evs = [
            {"ev": "entry", "sym": "AUSDT", "side": "long", "book": "optimal", "pos_at": T, "qty": 0.5, "px": 100.0,
             "avg": 100.0, "margin_usd": 25.0, "lev": 8.0, "take_px": 104.0, "floor_px": 80.0, "liq_px": 78.0,
             "term_ts": T + 72 * 3600, "fee_usd": 0.03, "slip_bp": 1.2, "px_ref": 99.99},
            {"ev": "take_set", "sym": "AUSDT", "side": "long", "pos_at": T, "px": 104.0, "qty": 0.5},
            {"ev": "rung", "sym": "AUSDT", "side": "long", "pos_at": T, "qty": 0.51, "px": 97.0,
             "avg": 98.49, "margin_usd": 25.0, "lev": 8.0, "take_px": 102.43, "floor_px": 85.0, "liq_px": 83.0, "fee_usd": 0.03},
            {"ev": "take_set", "sym": "AUSDT", "side": "long", "pos_at": T, "px": 102.43, "qty": 1.01},
            {"ev": "entry", "sym": "SUSDT", "side": "short", "book": "optimal_h", "pos_at": T + 60, "qty": 3.0, "px": 2.0,
             "avg": 2.0, "margin_usd": 6.25, "lev": 4.0, "take_px": 1.8, "floor_px": 2.2, "liq_px": 2.5, "fee_usd": 0.003},
            {"ev": "take", "sym": "SUSDT", "side": "short", "pos_at": T + 60, "px": 1.8, "pnl_usd": 0.59, "pnl_bp": 98.0},
            {"ev": "entry", "sym": "DRYUSDT", "side": "long", "pos_at": T, "qty": 1.0, "px": 1.0, "mode": "dry"},
        ]
        with open(os.path.join(d, "events.jsonl"), "w") as f:
            for i, e in enumerate(evs, 1):
                f.write(json.dumps(dict({"mode": "live"}, **e, seq=i, ts=T + 100 + i)) + "\n")
        import tradelog as TL
        TL.ingest(app.db, root, log=lambda *a: None)
        with open(os.path.join(d, "ladder_status.json"), "w") as f:
            json.dump({"at_ms": time.time() * 1000, "positions": [
                {"sym": "AUSDT", "pos_at": T, "qty": 1.01, "upnl_usd": 1.5, "fee_usd": 0.06, "realized_part_usd": 0.0,
                 "mark_px": 99.97, "mark_at_ms": T * 1000, "take_px": 102.43, "floor_px": 85.0, "liq_px": 83.0}]}, f)
        code, r = app.live_positions(acc)
        assert code == 200 and r["open"] == 1 and r["closed"] == 1, r
        a, s_ = r["positions"]
        assert a["sym"] == "AUSDT" and a["state"] == "open" and a["depth"] == 2 and a["cell"] == "optimal_h:1000"
        assert [w["qty"] for w in a["walk"]] == [0.5, 1.01] and a["walk"][1]["avg"] == 98.49
        assert a["walk"][0]["take"] == 104.0 and a["walk"][1]["take"] == 102.43, "цель после каждого рунга"
        assert abs(a["fills"][0][2] - 0.5 * 100.0 / 200.0) < 1e-12, "доля рунга — от нотионала маржа × плечо"
        assert abs(a["mark_usd"] - (1.5 - 0.06)) < 1e-12 and abs(a["mark_frac"] - 1.44 / 25.0) < 1e-12
        assert a["levels"]["floor_px"] == 85.0 and a["at"] == T + 101 and a["pos_at"] == T
        assert s_["state"] == "closed" and s_["exit"] == "тейк" and s_["usd"] == 0.59 and abs(s_["pnl_frac"] - 0.59 / 6.25) < 1e-12
        assert all(p["sym"] != "DRYUSDT" for p in r["positions"]), "сухая запись — не позиция"
        vs = s_["vs_paper"]
        # шорт: бумага продала по 2.02, живой по 2.00 — дешевле, хуже на 0.99 %;
        # откупили 1.80 против 1.81 бумаги — лучше: стоимость выхода −0.55 %
        assert abs(vs["entry_cost_pct"] - (2.02 - 2.0) / 2.02 * 100) < 1e-9, vs
        assert abs(vs["exit_cost_pct"] - (1.8 - 1.81) / 1.81 * 100) < 1e-9, vs
        assert abs(vs["paper_usd"] - 0.1 * 6.25) < 1e-9 and abs(vs["diff_usd"] - (0.59 - 0.625)) < 1e-9, vs
        assert s_["paper"]["exit"] == "тейк" and s_["paper"]["state"] == "closed"
        va = a["vs_paper"]
        assert abs(va["entry_cost_pct"] - (100.0 - 99.8) / 99.8 * 100) < 1e-9 and va["exit_cost_pct"] is None
        assert abs(va["paper_usd"] - 2.1 / 42.0 * 25.0) < 1e-9 and abs(va["diff_usd"] - (1.44 - 1.25)) < 1e-9, va
        pv = r["pnl"]["vs_paper"]
        assert pv["matched_n"] == 2 and abs(pv["diff_usd"] - (0.59 - 0.625 + 1.44 - 1.25)) < 1e-9, pv
        pn = r["pnl"]
        assert pn["realized_usd"] == 0.59 and abs(pn["open_usd"] - 1.44) < 1e-9 and abs(pn["total_usd"] - 2.03) < 1e-9, pn
        assert pn["deposit_usd"] == 1000.0 and abs(pn["total_pct"] - 0.203) < 1e-9 and pn["closed_n"] == 1
        assert pn["open_n"] == 1 and pn["wins_n"] == 1 and pn["open_unmarked"] == 0
        # нет статуса исполнителя — отметки нет, причина словами
        os.remove(os.path.join(d, "ladder_status.json"))
        a = app.live_positions(acc)[1]["positions"][0]
        assert "mark_usd" not in a and a["mark_why"] == "исполнитель не прислал статус"
        # бумага не считала час — причина словами
        dca["books"]["optimal_h:1000"]["trades"] = []
        dca["books"]["optimal_h:1000"]["open"] = {"positions": [{"sym": "ZUSDT", "at": T - 3600}]}
        app._dca = {"at": 0.0, "data": None}
        a = app.live_positions(acc)[1]["positions"][0]
        assert a["paper_why"] == "бумага ещё не считала этот час" and "vs_paper" not in a, a.get("paper_why")
        pn = app.live_positions(acc)[1]["pnl"]
        assert pn["open_unmarked"] == 1 and pn["open_usd"] == 0.0 and pn["total_usd"] == 0.59, "без отметки — названо числом"
    print("ok  живые позиции: форма строки книги, доливы с целью, исход словом бумаги, отметка исполнителя нетто")


def test_supervisor_starts_armed_subs_with_key_on_stdin_and_stops_unarmed():
    """Супервизор: подписке в live — ровно один процесс, ключ ТОЛЬКО трубой;
    первый подъём не читает сухие намерения; подписка вышла из live —
    мягкая остановка файлом STOP; сухие подписки не трогаются."""
    import ladder_run as LR
    with tempfile.TemporaryDirectory() as tmp:
        root = os.path.join(tmp, "exec")
        app, _ = _app(tmp, out=tmp, exec_root=root)
        acc = _login(app)
        st, k = app.add_key(acc, "bybit", "ABCD1234KEY", SECRET)
        st, a = app.add_subscription(acc, k["key_id"], "optimal_h", 1000)
        st, b = app.add_subscription(acc, k["key_id"], "pair_optimal", 1000)
        sa, sb = a["subscription_id"], b["subscription_id"]
        os.makedirs(os.path.join(root, sa))
        with open(os.path.join(root, sa, "intents.jsonl"), "w") as f:
            f.write(json.dumps({"seq": 7, "kind": "entry"}) + "\n")
        app.db.c.execute("UPDATE subscriptions SET mode='live' WHERE id=?", (sa,))
        started, stopped, built = [], [], []

        class P:
            pid = 4242

            def __init__(self, cmd, **kw):
                self.cmd = cmd
                self.kw = kw
                self.stdin = self
                self.data = b""

            def write(self, d):
                self.data += d

            def close(self):
                started.append((self.cmd, self.data))

        bin_path = os.path.join(tmp, "bot")
        with open(bin_path, "w") as f:
            f.write("x")
        r = LR.ensure(app.db, root=root, bin_path=bin_path, run={}, builder=lambda: built.append(1) or True,
                      starter=lambda db, sid, root, bin_path: LR.start(db, sid, root=root, bin_path=bin_path,
                                                                       opener=lambda db, s: ("KEYK", "SECS"), popen=P),
                      stopper=lambda sid, pids, root: stopped.append(sid) or True)
        assert r["started"] == 1 and len(started) == 1, (r, started)
        cmd, data = started[0]
        assert cmd[1:3] == ["ladder", "--dir"] and cmd[3].endswith(sa) and "--keys-stdin" in cmd
        assert cmd[cmd.index("--interval-sec") + 1] == "2", "такт 2 с — отметка позиции как можно чаще"
        assert "KEYK" not in " ".join(cmd) and "SECS" not in " ".join(cmd), "ключ не в аргументах"
        assert data == b"BYBIT_KEY=KEYK\nBYBIT_SECRET=SECS\n"
        assert json.load(open(os.path.join(root, sa, "ladder_state.json")))["seq_done"] == 7
        # работает — второй не запускается
        r = LR.ensure(app.db, root=root, bin_path=bin_path, run={sa: [111]}, builder=lambda: True,
                      starter=lambda *x, **y: started.append("лишний") or True, stopper=lambda *x, **y: True)
        assert r["started"] == 0 and len(started) == 1
        # подписка вышла из live — мягкая остановка; сухая b не трогается
        app.db.c.execute("UPDATE subscriptions SET mode='dry' WHERE id=?", (sa,))
        LR.ensure(app.db, root=root, bin_path=bin_path, run={sa: [111]}, builder=lambda: True,
                  starter=lambda *x, **y: True, stopper=lambda sid, pids, root: stopped.append(sid) or True)
        assert stopped == [sa] and sb not in stopped
        # мягкая остановка — файл STOP
        assert LR.stop(sa, [999999999], root=root, wait_s=1) is True
        assert os.path.exists(os.path.join(root, sa, "STOP"))
        # разбор pgrep
        got = LR.running(pgrep=lambda: f"123 /x/bot ladder --dir {root}/{sa} --base B --keys-stdin\n456 python other\n")
        assert got == {sa: [123]}, got
    print("ok  супервизор: один процесс на live, ключ трубой, сухие намерения не исполняются, STOP при выходе из live")


TESTS = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]

if __name__ == "__main__":
    import traceback
    bad = 0
    for t in TESTS:
        try:
            t()
            print("ok", t.__name__)
        except Exception:                                      # noqa: BLE001
            bad += 1
            print("FAIL", t.__name__)
            traceback.print_exc()
    sys.exit(1 if bad else 0)
