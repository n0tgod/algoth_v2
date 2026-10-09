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
    app = SV.App(os.path.join(tmp, "app.sqlite"), pub, operator_token="OPTOKEN",
                 venue=venue or FakeVenue(), dca_fetch=lambda full=None: DCA, **kw)
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
            assert _http(port, "POST", f"/api/v1/subscriptions/{s['subscription_id']}/arm", {}, token=tok)[0] == 501
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
        st, tr = app.list_trades(acc)
        assert st == 200 and [t["seq"] for t in tr["trades"]] == [3, 2, 1] and tr["by_mode"] == {"dry": 3}
        t3 = tr["trades"][0]
        assert t3["kind"] == "take" and t3["words"] == "Closed at target" and t3["pnl_usd"] == 3.9
        assert t3["pushed"]["sent"] == 1 and t3["pushed"]["results"][0]["env"] == "prod"
        # лента по since — только новое
        st, tr2 = app.list_trades(acc, since=tr["trades"][-1]["id"])
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
        st, tr = app.list_trades(acc)
        assert tr["by_mode"] == {"dry": 4, "test": 1} and tr["executor_running"] is False
        assert SECRET not in json.dumps(tr)


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
