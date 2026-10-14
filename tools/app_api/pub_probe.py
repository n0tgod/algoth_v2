#!/usr/bin/env python3
"""Проверка публичного свода API с самого сервера (спека 16 L1).

Ходит на https://127.0.0.1:443/api/v1/pub/… как приложение (без ключа
страниц, без сессии), печатает код, размер и главное поле ответа; плюс
две отказные проверки (чужой маршрут, чужой параметр). Сертификат
самоподписанный — проверка подписи здесь отключена: это свой же сервер
на петле, закрепление проверяет приложение.

    run tools/app_api/pub_probe.py
"""
import gzip
import json
import ssl
import sys
import urllib.error
import urllib.request

BASE = "https://127.0.0.1:443/api/v1/pub/"
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE


def get(path, gz=True):
    req = urllib.request.Request(BASE + path)
    if gz:
        req.add_header("Accept-Encoding", "gzip")
    try:
        with urllib.request.urlopen(req, timeout=60, context=CTX) as r:
            raw = r.read()
            body = gzip.decompress(raw) if r.headers.get("Content-Encoding") == "gzip" else raw
            return r.status, len(raw), json.loads(body)
    except urllib.error.HTTPError as e:
        return e.code, 0, json.loads(e.read() or b"{}")


def main():
    bad = 0
    st, n, d = get("dca?focus=optimal:100")
    b = (d.get("books") or {}).get("optimal:100") or {}
    print(f"dca focus=optimal:100: {st}, {n} байт по сети, книг {len(d.get('books') or {})}, "
          f"сделок у книги в фокусе {len(b.get('trades') or [])}, рулеток {len(d.get('rulers') or [])}")
    bad += st != 200 or not b
    st, n, d = get("dca_marks?ruler=optimal&dep=100")
    print(f"dca_marks: {st}, {n} байт, known={d.get('known')}, строк {len(d.get('rows') or [])}")
    bad += st != 200
    st, n, d = get("candles?sym=BTCUSDT&hours=2")
    print(f"candles BTCUSDT 2 ч: {st}, {n} байт, sym={d.get('sym')}, баров {len(d.get('bars') or d.get('rows') or [])}")
    bad += st != 200
    for path, want in (("mem", 400), ("dca?k=x", 400), ("status", 400)):
        st, _n, d = get(path)
        print(f"{path}: {st} — {d.get('error')}")
        bad += st != want
    print("итог: " + ("всё сходится" if not bad else f"РАСХОЖДЕНИЙ {bad}"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
