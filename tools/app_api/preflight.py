#!/usr/bin/env python3
"""Предполётная проверка счёта подписки перед живыми сделками (спека 15
§7a.4, §10a). Печатает ЧИСЛА и ДА/НЕТ, никогда — ключ или секрет.

    run tools/app_api/preflight.py
    run tools/app_api/preflight.py --sub sub_xxx

Что проверяется: ключ открывается; тот же ли это счёт, что у X3
(отпечатки ключей, не сами ключи); тип счёта и режим маржи; эквити и
свободные деньги против кассы подписки; открытые позиции и заявки
счёта (чужие для исполнителя Ladder); режим позиций по открытым;
рубильник LIVE_ENABLED; живой ли процесс X3.
"""
import argparse
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bybit as BY                                           # noqa: E402
import db as DBM                                             # noqa: E402
import keys_local as KL                                      # noqa: E402

OUT = os.path.join(HERE, "out")


def account_info(key, secret):
    return BY._get("/v5/account/info", key, secret)


def wallet(key, secret):
    r = BY._get("/v5/account/wallet-balance", key, secret, {"accountType": "UNIFIED", "coin": "USDT"})
    for acc in r.get("list") or []:
        for c in acc.get("coin") or []:
            if c.get("coin") == "USDT":
                f = lambda k: float(c.get(k) or 0.0)            # noqa: E731
                return {"equity": f("equity"), "wallet": f("walletBalance"),
                        "total_avail": float(acc.get("totalAvailableBalance") or 0.0),
                        "im": float(acc.get("totalInitialMargin") or 0.0)}
    return None


def positions(key, secret):
    r = BY._get("/v5/position/list", key, secret, {"category": "linear", "settleCoin": "USDT", "limit": 200})
    out = []
    for p in r.get("list") or []:
        if float(p.get("size") or 0) != 0:
            out.append({"sym": p.get("symbol"), "side": p.get("side"), "size": float(p.get("size")),
                        "idx": int(p.get("positionIdx") or 0), "lev": p.get("leverage"),
                        "trade_mode": p.get("tradeMode")})
    return out


def orders(key, secret):
    r = BY._get("/v5/order/realtime", key, secret, {"category": "linear", "settleCoin": "USDT", "limit": 50})
    return [{"sym": o.get("symbol"), "side": o.get("side"), "link": (o.get("orderLinkId") or "")[:3]}
            for o in r.get("list") or []]


def check(db, s, log=print, update_equity=False):
    sid = s["id"]
    log(f"\n== подписка {sid}: {s['book']} {float(s['deposit']):g} $, режим {s['mode']}")
    st = json.loads(s["state_json"] or "{}")
    cash = float(s["deposit"]) + float(st.get("realized_usd") or 0.0)
    try:
        key, secret = KL.open_sub_key(db, sid)
    except KL.KeyError_ as e:
        log(f"ключ: НЕ открывается — {e}")
        return False
    x3 = KL.live_env_key()
    same = (KL.fingerprint(key) == KL.fingerprint(x3)) if x3 else None
    log(f"ключ: открывается; отпечаток {KL.fingerprint(key)}; ключ X3 (live.env) "
        + ("тот же самый" if same else "другой" if same is False else "не найден"))
    ok = True
    try:
        ai = account_info(key, secret)
        log(f"счёт: unifiedMarginStatus {ai.get('unifiedMarginStatus')}, marginMode {ai.get('marginMode')}, "
            f"isMasterTrader {ai.get('isMasterTrader')}")
    except BY.VenueError as e:
        log(f"счёт: account/info не читается — {e}")
        ok = False
    try:
        w = wallet(key, secret)
        if w is None:
            log("деньги: в ответе нет USDT")
            ok = False
        else:
            log(f"деньги: эквити {w['equity']:.2f} $, кошелёк {w['wallet']:.2f} $, доступно {w['total_avail']:.2f} $, "
                f"занято маржой {w['im']:.2f} $; касса подписки {cash:.2f} $ — "
                + ("хватает" if w["equity"] >= cash else "НЕ хватает"))
            ok = ok and w["equity"] >= cash
            if update_equity:
                db.set_equity(s["key_id"], w["equity"])
    except BY.VenueError as e:
        log(f"деньги: не читаются — {e}")
        ok = False
    try:
        ps = positions(key, secret)
        log(f"позиции на счёте: {len(ps)}" + ("" if not ps else " — " + "; ".join(
            f"{p['sym']} {p['side']} {p['size']} idx {p['idx']} плечо {p['lev']} tradeMode {p['trade_mode']}" for p in ps)))
        modes = {p["idx"] for p in ps}
        log("режим позиций по открытым: " + ("нет открытых — не измерен (исполнитель определит первой заявкой)"
                                            if not ps else ("хедж" if modes & {1, 2} else "односторонний")))
    except BY.VenueError as e:
        log(f"позиции: не читаются — {e}")
        ok = False
    try:
        os_ = orders(key, secret)
        log(f"заявки на счёте: {len(os_)}" + ("" if not os_ else " — " + "; ".join(
            f"{o['sym']} {o['side']} метка {o['link']}…" for o in os_)))
    except BY.VenueError as e:
        log(f"заявки: не читаются — {e}")
    return ok


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", default=os.path.join(OUT, "app.sqlite"))
    ap.add_argument("--sub", default=None)
    ap.add_argument("--update-equity", action="store_true", help="записать измеренное эквити в базу (кнопка приложения)")
    a = ap.parse_args(argv)
    db = DBM.DB(a.db)
    live_on = os.path.exists(os.path.join(OUT, "LIVE_ENABLED"))
    print(f"рубильник LIVE_ENABLED: {'включён' if live_on else 'выключен'}")
    x3 = subprocess.run(["pgrep", "-f", "bot live --s8"], capture_output=True, text=True).stdout.split()
    print(f"процесс X3 (bot live): {'жив, pid ' + ','.join(x3) if x3 else 'не запущен'}")
    subs = db.c.execute("SELECT * FROM subscriptions WHERE status='active'").fetchall()
    print(f"активных подписок {len(subs)}")
    good = True
    for s in subs:
        if a.sub and s["id"] != a.sub:
            continue
        good = check(db, s, update_equity=a.update_equity) and good
    print("\nитог: " + ("годен" if good else "НЕ годен — причины выше"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
