"""Пуши APNs для событий живого исполнителя (спека 15 §7.5).

Решение владельца 2026-10-09: пуш на КАЖДОЕ действие исполнителя —
вход, долив, закрытие любого вида, отказ входа, остановка, расхождение
сверки. Текст пуша — слова события с числами; денег пуш не считает,
он печатает то, что записал исполнитель.

Транспорт — APNs по HTTP/2 с токеном разработчика (ключ `.p8`, Key ID,
Team ID): запрос делает `curl --http2` системы (nghttp2 есть у curl
Ubuntu), стандартная библиотека Python HTTP/2 не умеет, а тащить ради
одного запроса пакет в `.venv` — лишняя зависимость у процесса на 443.
Подпись JWT ES256 — PyJWT, тот же, что проверяет вход Apple.

Ключ APNs лежит в `out/apns.json` (600) и кладётся оператором через
приложение (`POST push/config`); в git не идёт. Это НЕ ключ биржи:
процесс API видит его открытым, потому что сам им подписывает — к
деньгам он доступа не даёт, худшее с ним — чужой пуш на свой телефон.

Проверяемость без сети: `payload_for` и `jwt_for` — чистые функции;
`send` принимает подменяемый `runner`.
"""
import json
import os
import subprocess
import time

HOSTS = {"prod": "https://api.push.apple.com",
         "sandbox": "https://api.sandbox.push.apple.com"}
TOPIC_DEFAULT = "pl.mdsauto.algoth"
JWT_TTL = 50 * 60                      # Apple просит обновлять не реже часа
CURL_TIMEOUT = 15

# Слова событий — английские: язык экрана приложения английский
# (решение владельца 2026-10-09), и пуш читается тем же глазом.
KIND_WORDS = {
    "entry": "Entry", "rung": "Averaging", "take_set": "Target moved",
    "take": "Closed at target", "floor": "Closed at floor", "term": "Closed on time",
    "market": "Closed by market guard", "cmd_close": "Closed by command",
    "reject": "Entry not filled", "halt": "Executor halted", "resume": "Executor resumed",
    "mismatch": "Reconcile mismatch", "test": "Test event"}
# Что пушится: ВСЁ, что записал исполнитель (решение владельца). Список
# здесь, чтобы будущий фильтр по видам был правкой одной строки.
PUSHED_KINDS = set(KIND_WORDS)


def config_path(out):
    return os.path.join(out, "apns.json")


def load_config(out):
    try:
        with open(config_path(out), encoding="utf-8") as f:
            c = json.load(f)
    except (OSError, ValueError):
        return None
    if not all(c.get(k) for k in ("team_id", "key_id", "p8")):
        return None
    c.setdefault("topic", TOPIC_DEFAULT)
    return c


def save_config(out, team_id, key_id, p8, topic=None):
    """Проверяет ключ подписью (битый `.p8` отвергается словами), пишет 600."""
    team_id, key_id = str(team_id or "").strip(), str(key_id or "").strip()
    p8 = str(p8 or "").strip().replace("\\n", "\n")
    if not team_id or not key_id or "PRIVATE KEY" not in p8:
        raise ValueError("нужны Team ID, Key ID и содержимое файла .p8 (-----BEGIN PRIVATE KEY-----)")
    jwt_for(team_id, key_id, p8)                        # ValueError/TypeError при битом ключе
    os.makedirs(out, exist_ok=True)
    path = config_path(out)
    # Тема без явного значения — ПРЕЖНЯЯ, если ключ уже был: замена ключа
    # не вправе молча вернуть тему из project.yml (10.10: Bundle ID сборки
    # `algoth`, а не `pl.mdsauto.algoth` — первый пуш ответил TopicDisallowed)
    was = load_config(out)
    topic = (topic or (was or {}).get("topic") or TOPIC_DEFAULT).strip()
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"team_id": team_id, "key_id": key_id, "p8": p8,
                   "topic": topic, "saved": time.time()}, f)
    os.chmod(path, 0o600)
    return {"team_id": team_id[:3] + "…", "key_id": key_id, "topic": topic}


def public_config(out):
    c = load_config(out)
    if c is None:
        return {"configured": False}
    return {"configured": True, "key_id": c["key_id"], "team_id": c["team_id"][:3] + "…",
            "topic": c["topic"], "saved": c.get("saved")}


def jwt_for(team_id, key_id, p8, now=None):
    import jwt                                              # PyJWT, уже в .venv
    now = int(now if now is not None else time.time())
    try:
        return jwt.encode({"iss": team_id, "iat": now}, p8, algorithm="ES256",
                          headers={"kid": key_id})
    except Exception as e:                                  # noqa: BLE001
        raise ValueError(f"ключ APNs не подписывает: {e}") from None


def _words(t):
    """Слова пуша из записи сделки (словарь строки `trades`)."""
    kind = t.get("kind") or "?"
    what = KIND_WORDS.get(kind, kind)
    sym = (t.get("sym") or "").replace("USDT", "")
    side = t.get("side") or ""
    parts = []
    if t.get("margin_usd") is not None and kind in ("entry", "rung"):
        parts.append(f"{float(t['margin_usd']):.2f} $")
    if t.get("lev") is not None and kind == "entry":
        parts.append(f"×{float(t['lev']):g}")
    if t.get("px") is not None:
        parts.append(f"@ {float(t['px']):g}")
    if t.get("avg") is not None and kind == "rung":
        parts.append(f"avg {float(t['avg']):g}")
    if t.get("depth") not in (None, ""):
        parts.append(f"rung {t['depth']}")
    if t.get("pnl_usd") is not None:
        parts.append(f"{float(t['pnl_usd']):+.2f} $")
    if t.get("pnl_bp") is not None:
        parts.append(f"{float(t['pnl_bp']):+.0f} bp")
    if t.get("reason"):
        parts.append(str(t["reason"]))
    mode = t.get("mode") or "dry"
    tag = "" if mode == "live" else f" [{mode}]"
    title = f"{what}{tag}" + (f" · {sym} {side}".rstrip() if sym else "")
    body = " · ".join(parts) if parts else what
    return title, body


def payload_for(trade, book=None):
    """APNs-полезная нагрузка по записи сделки; `book` — подпись книги."""
    title, body = _words(trade)
    alert = {"title": title, "body": body}
    if book:
        alert["subtitle"] = str(book)
    # поля без значения не пишутся вовсе: пустая строка в пуше — не прочерк
    return _strip({"aps": {"alert": alert, "sound": "default",
                           "thread-id": trade.get("subscription_id") or "algoth",
                           "category": f"algoth.{trade.get('kind') or 'event'}"},
                   "trade_id": trade.get("id"), "kind": trade.get("kind"), "mode": trade.get("mode")})


class Sender:
    """Отправка с кешем JWT; `runner` подменяется в проверках."""

    def __init__(self, out, runner=None):
        self.out = out
        self.runner = runner or self._curl
        self._jwt = (0.0, None, None)                       # (когда, key_id, токен)

    def token(self, cfg):
        at, kid, tok = self._jwt
        if tok and kid == cfg["key_id"] and time.time() - at < JWT_TTL:
            return tok
        tok = jwt_for(cfg["team_id"], cfg["key_id"], cfg["p8"])
        self._jwt = (time.time(), cfg["key_id"], tok)
        return tok

    @staticmethod
    def _curl(url, headers, body):
        cmd = ["curl", "-sS", "--http2", "-m", str(CURL_TIMEOUT), "-o", "-", "-w", "\n%{http_code}",
               "-X", "POST", url, "--data-binary", "@-"]
        for k, v in headers.items():
            cmd += ["-H", f"{k}: {v}"]
        try:
            r = subprocess.run(cmd, input=body.encode("utf-8"), capture_output=True, timeout=CURL_TIMEOUT + 5)
        except (OSError, subprocess.TimeoutExpired) as e:
            return 0, f"curl: {e}"
        out = r.stdout.decode("utf-8", "replace").rsplit("\n", 1)
        try:
            code = int(out[-1].strip() or 0)
        except ValueError:
            code = 0
        text = out[0] if len(out) > 1 else ""
        if r.returncode and not code:
            return 0, f"curl exit {r.returncode}: {r.stderr.decode('utf-8', 'replace')[:200]}"
        return code, text

    def send(self, device_token, env, payload, cfg=None):
        """→ {"status": код APNs, "reason": причина Apple или слова, "dead": токен мёртв}."""
        cfg = cfg or load_config(self.out)
        if cfg is None:
            return {"status": 0, "reason": "APNs key not configured", "dead": False}
        host = HOSTS.get(env or "prod", HOSTS["prod"])
        headers = {"authorization": f"bearer {self.token(cfg)}", "apns-topic": cfg["topic"],
                   "apns-push-type": "alert", "apns-priority": "10", "apns-expiration": "0",
                   "content-type": "application/json"}
        body = json.dumps(_strip(payload), ensure_ascii=False)
        code, text = self.runner(f"{host}/3/device/{device_token}", headers, body)
        reason = None
        if text:
            try:
                reason = json.loads(text).get("reason")
            except ValueError:
                reason = text[:120]
        if code == 200:
            return {"status": 200, "reason": None, "dead": False}
        dead = code == 410 or reason in ("BadDeviceToken", "Unregistered", "DeviceTokenNotForTopic")
        words = reason or f"HTTP {code}"
        if reason == "TopicDisallowed":
            # 10.10: тема из project.yml не совпала с Bundle ID сборки
            words = (f"TopicDisallowed: тема {cfg['topic']!r} не разрешена ключу — "
                     "задайте Bundle ID приложения как тему (Replace APNs key → Bundle ID)")
        return {"status": code, "reason": words, "dead": dead}


def _strip(o):
    if isinstance(o, dict):
        return {k: _strip(v) for k, v in o.items() if v is not None}
    return o
