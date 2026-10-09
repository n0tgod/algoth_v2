"""Хранилище API приложения: SQLite с WAL (спека 15 §7a.1).

Таблицы: аккаунты, сессии (токен хранится хешем), ключи биржи (только
конверт и первые знаки), подписки на ячейки, события по аккаунту,
одноразовые nonce команд. Секретов в открытом виде здесь нет нигде.
"""
import hashlib
import json
import os
import secrets
import sqlite3
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
  id TEXT PRIMARY KEY, created REAL NOT NULL, role TEXT NOT NULL,
  apple_sub TEXT UNIQUE, email TEXT, status TEXT NOT NULL DEFAULT 'active');
CREATE TABLE IF NOT EXISTS sessions (
  token_hash TEXT PRIMARY KEY, account_id TEXT NOT NULL, created REAL NOT NULL,
  expires REAL NOT NULL, device TEXT, last_seen REAL);
CREATE TABLE IF NOT EXISTS exchange_keys (
  id TEXT PRIMARY KEY, account_id TEXT NOT NULL, venue TEXT NOT NULL,
  key_prefix TEXT NOT NULL, cipher BLOB, perms_json TEXT NOT NULL,
  ip_ok INTEGER NOT NULL, checked REAL NOT NULL, status TEXT NOT NULL,
  created REAL NOT NULL, equity_usd REAL, equity_at REAL);
CREATE TABLE IF NOT EXISTS subscriptions (
  id TEXT PRIMARY KEY, account_id TEXT NOT NULL, key_id TEXT NOT NULL,
  book TEXT NOT NULL, deposit REAL NOT NULL, mode TEXT NOT NULL,
  state_json TEXT NOT NULL DEFAULT '{}', created REAL NOT NULL,
  armed_at REAL, armed_by TEXT, status TEXT NOT NULL DEFAULT 'active');
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, account_id TEXT,
  kind TEXT NOT NULL, text TEXT NOT NULL, data_json TEXT);
CREATE TABLE IF NOT EXISTS nonces (nonce TEXT PRIMARY KEY, ts REAL NOT NULL);
CREATE INDEX IF NOT EXISTS ev_acc ON events(account_id, id);
"""
SESSION_DAYS = 30


def new_id(prefix):
    return f"{prefix}_{secrets.token_hex(8)}"


def token_hash(tok):
    return hashlib.sha256(tok.encode("utf-8")).hexdigest()


class DB:
    def __init__(self, path):
        self.path = path
        if path != ":memory:":
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.c = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.c.row_factory = sqlite3.Row
        if path != ":memory:":
            self.c.execute("PRAGMA journal_mode=WAL")
        self.c.executescript(SCHEMA)
        if path != ":memory:":
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass

    # ------------------------------------------------------------ аккаунты
    def accounts_count(self):
        return int(self.c.execute("SELECT COUNT(*) FROM accounts").fetchone()[0])

    def account(self, acc_id):
        return self.c.execute("SELECT * FROM accounts WHERE id=?", (acc_id,)).fetchone()

    def account_by_apple(self, sub):
        return self.c.execute("SELECT * FROM accounts WHERE apple_sub=?", (sub,)).fetchone()

    def operator(self):
        return self.c.execute("SELECT * FROM accounts WHERE role='operator' ORDER BY created LIMIT 1").fetchone()

    def create_account(self, role, apple_sub=None, email=None):
        aid = new_id("acc")
        self.c.execute("INSERT INTO accounts(id,created,role,apple_sub,email) VALUES(?,?,?,?,?)",
                       (aid, time.time(), role, apple_sub, email))
        return aid

    def link_apple(self, acc_id, sub, email=None):
        self.c.execute("UPDATE accounts SET apple_sub=?, email=COALESCE(?, email) WHERE id=?",
                       (sub, email, acc_id))

    # ------------------------------------------------------------ сессии
    def new_session(self, acc_id, device=None):
        tok = secrets.token_urlsafe(32)
        now = time.time()
        self.c.execute("INSERT INTO sessions(token_hash,account_id,created,expires,device,last_seen) VALUES(?,?,?,?,?,?)",
                       (token_hash(tok), acc_id, now, now + SESSION_DAYS * 86400, device, now))
        return tok

    def session(self, tok):
        if not tok:
            return None
        r = self.c.execute("SELECT * FROM sessions WHERE token_hash=?", (token_hash(tok),)).fetchone()
        if r is None or r["expires"] < time.time():
            return None
        self.c.execute("UPDATE sessions SET last_seen=? WHERE token_hash=?", (time.time(), r["token_hash"]))
        return r

    def drop_session(self, tok):
        self.c.execute("DELETE FROM sessions WHERE token_hash=?", (token_hash(tok),))

    # ------------------------------------------------------------ ключи
    def add_key(self, acc_id, venue, prefix, cipher, perms, ip_ok, equity=None):
        kid = new_id("key")
        now = time.time()
        self.c.execute("""INSERT INTO exchange_keys(id,account_id,venue,key_prefix,cipher,perms_json,ip_ok,checked,status,created,equity_usd,equity_at)
                          VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                       (kid, acc_id, venue, prefix, cipher, json.dumps(perms, ensure_ascii=False),
                        1 if ip_ok else 0, now, "ok", now, equity, now if equity is not None else None))
        return kid

    def keys_of(self, acc_id):
        return self.c.execute("SELECT * FROM exchange_keys WHERE account_id=? AND status!='revoked' ORDER BY created",
                              (acc_id,)).fetchall()

    def key(self, kid, acc_id=None):
        if acc_id is None:
            return self.c.execute("SELECT * FROM exchange_keys WHERE id=?", (kid,)).fetchone()
        return self.c.execute("SELECT * FROM exchange_keys WHERE id=? AND account_id=?", (kid, acc_id)).fetchone()

    def set_equity(self, kid, equity):
        self.c.execute("UPDATE exchange_keys SET equity_usd=?, equity_at=? WHERE id=?", (equity, time.time(), kid))

    def revoke_key(self, kid):
        self.c.execute("UPDATE exchange_keys SET status='revoked', cipher=NULL WHERE id=?", (kid,))

    # ------------------------------------------------------------ подписки
    def add_subscription(self, acc_id, key_id, book, deposit, state=None):
        sid = new_id("sub")
        self.c.execute("""INSERT INTO subscriptions(id,account_id,key_id,book,deposit,mode,state_json,created)
                          VALUES(?,?,?,?,?,?,?,?)""",
                       (sid, acc_id, key_id, book, float(deposit), "dry",
                        json.dumps(state or {}, ensure_ascii=False), time.time()))
        return sid

    def subscriptions_of(self, acc_id):
        return self.c.execute("SELECT * FROM subscriptions WHERE account_id=? AND status='active' ORDER BY created",
                              (acc_id,)).fetchall()

    def subscription(self, sid, acc_id):
        return self.c.execute("SELECT * FROM subscriptions WHERE id=? AND account_id=? AND status='active'",
                              (sid, acc_id)).fetchone()

    def subs_on_key(self, key_id, live_only=False):
        q = "SELECT * FROM subscriptions WHERE key_id=? AND status='active'" + (" AND mode='live'" if live_only else "")
        return self.c.execute(q, (key_id,)).fetchall()

    def set_sub_state(self, sid, state):
        self.c.execute("UPDATE subscriptions SET state_json=? WHERE id=?", (json.dumps(state, ensure_ascii=False), sid))

    def close_subscription(self, sid):
        self.c.execute("UPDATE subscriptions SET status='closed' WHERE id=?", (sid,))

    # ------------------------------------------------------------ события
    def event(self, acc_id, kind, text, data=None):
        self.c.execute("INSERT INTO events(ts,account_id,kind,text,data_json) VALUES(?,?,?,?,?)",
                       (time.time(), acc_id, kind, text, json.dumps(data, ensure_ascii=False) if data is not None else None))

    def events_of(self, acc_id, since=0, limit=200):
        return self.c.execute("SELECT * FROM events WHERE account_id=? AND id>? ORDER BY id LIMIT ?",
                              (acc_id, int(since), int(limit))).fetchall()

    # ------------------------------------------------------------ nonce
    def nonce_once(self, nonce, window=120):
        now = time.time()
        self.c.execute("DELETE FROM nonces WHERE ts<?", (now - 2 * window,))
        try:
            self.c.execute("INSERT INTO nonces(nonce,ts) VALUES(?,?)", (nonce, now))
            return True
        except sqlite3.IntegrityError:
            return False
