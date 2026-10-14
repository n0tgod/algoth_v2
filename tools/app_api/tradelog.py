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
import re
import sys
import time

import push as PUSH

TEST_PREFIX = "_test_"
RESEARCH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "research")


def rules():
    """Правила книг — лениво, одним ядром с бумагой (`rules.title_en`)."""
    p = os.path.join(RESEARCH, "dca_paper")
    if p not in sys.path:
        sys.path.insert(0, p)
    import rules as R                                        # noqa: E402
    return R


# Слова исполнителя — по-английски на ПОКАЗЕ (спека 16 L5): журнал не
# переписывается (правило проекта), исполнитель пишет по-русски; показ
# переводит известные формы, переменная часть (ошибка биржи, числа)
# остаётся как есть. Незнакомая форма — как есть, и это видно (русский
# текст), а не тихая подмена. Порядок важен: частные формы раньше общих.
REASON_EN = [(re.compile(a), b) for a, b in (
    (r"^стоп пола на бирже не встал: (.*) — пол держит исполнитель$",
     r"exchange stop for the floor was not placed: \1 — the executor watches the floor"),
    (r"^пол (\S+) дальше предела биржи \(стоп не дальше 10 % от цены\) — пол держит исполнитель, стоп встанет, когда цена подойдёт$",
     r"floor \1 is beyond the exchange limit (stop within 10 % of price) — the executor watches it; the stop is placed when the price comes closer"),
    (r"^пол стоит стоп-заявкой на бирже \(последняя цена, на всю позицию\)$",
     "floor placed as an exchange stop order (last price, whole position)"),
    (r"^на бирже стоп (.*) вместо (.*) — ставлю заново$", r"exchange stop is \1 instead of \2 — placing it again"),
    (r"^пауза снята файлом RESUME \(была: (.*)\)$", r"pause lifted (was: \1)"),
    (r"^сухой режим: заявка сформирована, на биржу не отправлена$", "dry run: order prepared, not sent to the exchange"),
    (r"^исполнено частично: (\S+) из (\S+)$", r"partially filled: \1 of \2"),
    (r"^рунг (\d+) мельче минимума биржи — не ставится$", r"rung \1 is below the exchange minimum — not placed"),
    (r"^рунг (\d+) не поставлен: (.*)$", r"rung \1 not placed: \2"),
    (r"^выход \((\S+)\) отвергнут: (.*) — повтор следующим тактом$", r"exit (\1) rejected: \2 — retrying"),
    (r"^намерение без имени, стороны, плеча, маржи или рунгов$", "decision without symbol, side, leverage, margin or rungs"),
    (r"^намерение с пустыми рунгами или нулевой маржой$", "decision with empty rungs or zero margin"),
    (r"^намерение устарело: (\S+) мин после расчёта — цена ушла$", r"decision expired: \1 min after it was computed — the price moved"),
    (r"^входы выключены \(NO_ENTRIES\)$", "new entries are stopped"),
    (r"^входы на паузе: (.*)$", r"entries paused: \1"),
    (r"^имя уже в позиции этого исполнителя$", "this symbol is already in a position of this subscription"),
    (r"^справочник не читается: (.*)$", r"instrument info unavailable: \1"),
    (r"^цены не читаются: (.*)$", r"prices unavailable: \1"),
    (r"^середины нет$", "no mid price"),
    (r"^база мельче минимума биржи: (.*) при мин\. лоте (\S+) и мин\. нотионале (\S+) \$$",
     r"base entry below the exchange minimum: \1, min lot \2, min notional \3 $"),
    (r"^на счёте уже есть чужая позиция по этому имени$", "the account already has another position in this symbol"),
    (r"^позиции счёта не читаются: (.*)$", r"account positions unavailable: \1"),
    (r"^плечо (\S+)× не выставилось: (.*); предел площадки (\S+)× тоже: (.*)$",
     r"leverage \1× was not set: \2; the exchange maximum \3× neither: \4"),
    (r"^плечо (\S+)× не выставилось: (.*)$", r"leverage \1× was not set: \2"),
    (r"^заявка входа отвергнута: (.*)$", r"entry order rejected: \1"),
    (r"^статус входа не читается: (.*)$", r"entry status unavailable: \1"),
    (r"^статус входа не окончателен \((\S+), исполнено (\S+)\) — имя под присмотром сверки$",
     r"entry status not final (\1, filled \2) — the symbol is watched by reconciliation"),
    (r"^IOC не исполнилась в потолке (\S+) б\.п\. от середины: bid (\S+), ask (\S+), лимит (\S+), статус (\S+)$",
     r"entry not filled within \1 bp of mid: bid \2, ask \3, limit \4, status \5"),
    (r"^на счёте позиция (\S+) \((\S+)\) после входа неясного исхода — исполнитель её не ведёт; входы на паузе до RESUME$",
     r"the account holds \1 (\2) after an entry with unclear outcome — the executor does not manage it; entries paused"),
    (r"^цель (\S+) не встала: (.*)$", r"target for \1 was not placed: \2"),
    (r"^рунг (\S+): (.*)$", r"rung \1: \2"),
    (r"^цель (\S+): (.*)$", r"target \1: \2"),
    (r"^котировки не читаются: (.*)$", r"quotes unavailable: \1"),
    (r"^выход (\S+): цены не читаются, повтор: (.*)$", r"exit \1: prices unavailable, retrying: \2"),
    (r"^выход (\S+) \((\S+)\): IOC не исполнилась в потолке, повтор$", r"exit \1 (\2): not filled within the price limit, retrying"),
    (r"^выход (\S+): статус не читается: (.*)$", r"exit \1: status unavailable: \2"),
    (r"^сверка: позиции не читаются: (.*)$", r"reconciliation: positions unavailable: \1"),
    (r"^сверка (\S+): у исполнителя (\S+), у биржи (\S+)$", r"reconciliation \1: executor holds \2, the exchange \3"),
    (r"^пол сработал стоп-заявкой на бирже; деньги и цена — closed-pnl биржи$",
     "floor hit by the exchange stop order; money and price from the exchange’s closed P&L"),
    (r"^позиция закрыта при стоящем стопе пола; денег биржа не отдала — записан ноль с этой оговоркой$",
     "position closed while the floor stop was in place; the exchange returned no P&L — recorded as zero"),
    (r"^позиция закрыта вне исполнителя \(биржей или вручную\); деньги — closed-pnl биржи$",
     "position closed outside the executor (by the exchange or manually); money from the exchange’s closed P&L"),
    (r"^позиция закрыта вне исполнителя; денег биржа не отдала — записан ноль с этой оговоркой$",
     "position closed outside the executor; the exchange returned no P&L — recorded as zero"),
    (r"^открытые заявки не читаются: (.*)$", r"open orders unavailable: \1"),
)]


def reason_en(text):
    """Слова исполнителя по-английски для показа; незнакомое — как есть."""
    if not text:
        return text
    t = str(text)
    for rx, rep in REASON_EN:
        if rx.match(t):
            return rx.sub(rep, t, count=1)
    return t


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
    # подпись пуша — имя режима и сторона по-английски, как на экране (14.10)
    return f"{book_words(r['book'])} · {float(r['deposit']):g} $"


def book_words(key):
    """«Sigma · long» из ключа книги — та же карта, что у правил (`rules.title_en`)."""
    k = str(key)
    side = "both" if k.startswith("pair_") else "short" if k.endswith("_h") else "long"
    return f"{rules().title_en(k)} · {side}"


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
    t["reason"] = reason_en(t.get("reason"))              # пуш — словами показа
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
    # Отказ постановки стопа пола до 12.10 писался видом «reject» («Not
    # executed»), хотя вход состоялся. Запись журнала не переписывается —
    # показ называет её тем, чем она была (`stop_fail`); исходный вид рядом.
    if t["kind"] == "reject" and str(t.get("reason") or "").startswith("стоп пола на бирже не встал"):
        t["kind_raw"], t["kind"] = "reject", "stop_fail"
    if t.get("reason"):
        en = reason_en(t["reason"])
        if en != t["reason"]:
            t["reason_raw"], t["reason"] = t["reason"], en
    t["words"] = PUSH.KIND_WORDS.get(t["kind"], t["kind"])
    t["pushed"] = pushed
    t["extra"] = {k: v for k, v in data.items() if k not in t}
    return t
