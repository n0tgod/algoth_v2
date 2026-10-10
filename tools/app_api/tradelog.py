"""Журнал событий живого исполнителя → записи `trades` → пуши (спека 15 §7.6).

Формат журнала объявлен ДО исполнителя (Y2 пишет ровно его): файл
`bot/out/dca/<subscription_id>/events.jsonl` (и суточные части
`events-ГГГГ-ММ-ДД.jsonl`), строка — JSON с полями
    seq (int, растёт на 1), ts (UTC, секунды), ev (вид), mode (dry|live),
    sym, side, qty, px, margin_usd, lev, avg, depth ("k/n"), pnl_usd,
    pnl_bp, reason.
Виды: entry, rung, take_set, take, floor, term, market, cmd_close,
reject, halt, resume, mismatch. Журнал write-ahead: строка не
переписывается; приём читает файлы с начала и опирается на UNIQUE
(подписка, seq) — повтор чтения не дублирует ни сделку, ни пуш.

Пробный путь: `test_event` пишет строку вида `test` с `mode: "test"` в
каталог `_test_<account>`, и дальше она идёт той же дорогой — приём,
запись, пуш. Так проверяется весь канал до телефона без исполнителя;
в приложении запись помечена TEST и в деньгах не участвует.
"""
import glob
import json
import os
import time

import push as PUSH

TEST_PREFIX = "_test_"


def journal_dir(root, sub_id):
    return os.path.join(root, sub_id)


def journal_files(root, sub_id):
    d = journal_dir(root, sub_id)
    files = []
    if os.path.exists(os.path.join(d, "events.jsonl")):
        files.append(os.path.join(d, "events.jsonl"))
    files += sorted(glob.glob(os.path.join(d, "events-*.jsonl")))
    return files


def read_new(root, sub_id, after_seq):
    """Строки журнала подписки с `seq` больше данного, по порядку; битые —
    счётом, не молча."""
    out, bad = [], 0
    for path in journal_files(root, sub_id):
        try:
            with open(path, encoding="utf-8") as f:
                for ln in f:
                    ln = ln.strip()
                    if not ln:
                        continue
                    try:
                        ev = json.loads(ln)
                        seq = int(ev["seq"])
                        str(ev["ev"])
                    except (ValueError, KeyError, TypeError):
                        bad += 1
                        continue
                    if seq > after_seq:
                        out.append(ev)
        except OSError:
            continue
    out.sort(key=lambda e: int(e["seq"]))
    return out, bad


def ingest(db, root, log=print):
    """Все активные подписки плюс пробные каталоги → новые записи `trades`.
    Возвращает список id новых записей (их и пушить)."""
    new = []
    subs = [(s["id"], s["account_id"]) for s in db.c.execute(
        "SELECT id, account_id FROM subscriptions WHERE status='active'").fetchall()]
    # пробные каталоги: `_test_<account_id>`
    for d in glob.glob(os.path.join(root, TEST_PREFIX + "*")):
        sid = os.path.basename(d)
        subs.append((sid, sid[len(TEST_PREFIX):]))
    for sid, acc in subs:
        evs, bad = read_new(root, sid, db.last_seq(sid))
        if bad:
            log(f"журнал исполнителя {sid}: битых строк {bad}")
        for ev in evs:
            tid = db.add_trade(acc, sid, ev)
            if tid is not None:
                new.append(tid)
    return new


def book_label(db, sub_id):
    r = db.c.execute("SELECT book, deposit FROM subscriptions WHERE id=?", (sub_id,)).fetchone()
    if r is None:
        return "test" if sub_id.startswith(TEST_PREFIX) else None
    return f"{r['book']} · {float(r['deposit']):g} $"


def push_trade(db, sender, tid, log=print):
    """Пуш одной записи на все живые устройства аккаунта; итог — в запись
    (`pushed_json`): по каждому устройству статус и причина, чтобы «не
    пришло» было отличимо от «не посылали»."""
    t = dict(db.trade(tid))
    if t["kind"] not in PUSH.PUSHED_KINDS:
        db.trade_pushed(tid, {"skipped": "kind not pushed"})
        return {"skipped": "kind not pushed"}
    devs = db.devices_of(t["account_id"])
    if not devs:
        db.trade_pushed(tid, {"devices": 0})
        return {"devices": 0}
    payload = PUSH.payload_for(t, book=book_label(db, t["subscription_id"]))
    res = []
    for d in devs:
        r = sender.send(d["token"], d["env"], payload)
        res.append({"token": d["token"][:8] + "…", "env": d["env"], **r})
        if r["status"] != 200:
            db.device_failed(d["token"], r["reason"], dead=r["dead"])
            log(f"пуш {t['kind']} {t.get('sym')} → {d['token'][:8]}…: {r['status']} {r['reason']}")
    out = {"devices": len(devs), "sent": sum(1 for r in res if r["status"] == 200), "results": res}
    db.trade_pushed(tid, out)
    return out


def tick(db, root, sender, log=print):
    """Один такт: приём новых строк и пуш каждой. Возвращает число новых."""
    new = ingest(db, root, log=log)
    for tid in new:
        try:
            push_trade(db, sender, tid, log=log)
        except Exception as e:                              # noqa: BLE001
            log(f"пуш записи {tid} не удался: {e}")
            db.trade_pushed(tid, {"error": str(e)[:200]})
    return len(new)


def test_event(root, acc_id, text=None):
    """Пробная строка в пробный журнал аккаунта: вид `test`, `mode: test`."""
    sid = TEST_PREFIX + acc_id
    d = journal_dir(root, sid)
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, "events.jsonl")
    seq = 0
    try:
        with open(path, encoding="utf-8") as f:
            for ln in f:
                try:
                    seq = max(seq, int(json.loads(ln)["seq"]))
                except (ValueError, KeyError, TypeError):
                    pass
    except OSError:
        pass
    ev = {"seq": seq + 1, "ts": time.time(), "ev": "test", "mode": "test",
          "reason": text or "push channel check — not a trade"}
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(ev, ensure_ascii=False) + "\n")
    return sid, ev


def view(row):
    """Запись `trades` для приложения."""
    t = dict(row)
    data = {}
    try:
        data = json.loads(t.pop("data_json") or "{}")
    except ValueError:
        pass
    pushed = None
    try:
        pushed = json.loads(t.pop("pushed_json") or "null")
    except ValueError:
        pass
    t["words"] = PUSH.KIND_WORDS.get(t["kind"], t["kind"])
    t["pushed"] = pushed
    t["extra"] = {k: v for k, v in data.items() if k not in t}
    return t
