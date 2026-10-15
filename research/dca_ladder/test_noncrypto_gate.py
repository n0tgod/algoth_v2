"""Гейт Ladder отсекает не-крипто — по разметке площадки, не только списком.

Вопрос владельца 2026-10-15 (график CSOPSKHYNIX2L): Ladder держал перп
на акцию через выходные, хотя правило проекта не-крипто книгам со
сроком запрещает. После решения «отсекать» живой счёт держал AMZU —
фонд на Amazon, листинг 18.09: курируемый список отстал от волны на ~60
имён. Правило читает `symbolType` справочника площадки.

Кусается: (1) имя с разметкой stock/ETF/commodity/forex не проходит
гейт, хотя ни в списке, ни в снимке A1 его нет; (2) крипта с разметкой
'' и 'innovation' проходит; (3) справочник без поля (записи до 15.10) —
режет только список, не всё подряд; (4) отрицательный контроль: без
разметки AMZU проходит — значит ловит именно она.
"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "research"))
import run_d6 as D6                                           # noqa: E402
from common import universe_filter as UF                      # noqa: E402


def _instr(path, typed=True):
    rows = {"AMZUUSDT": "stock", "KODEX200USDT": "ETF", "EURUSDUSDT": "forex",
            "XAGUSDT": "commodity", "BTCUSDT": "", "AEONUSDT": "innovation"}
    d = {}
    for s, t in rows.items():
        d[s] = {"symbol": s, "launch_time": "1789727003000"}
        if typed:
            d[s]["symbol_type"] = t
    with open(path, "w", encoding="utf-8") as f:
        json.dump(d, f)


def test_exchange_marking_cuts_what_the_list_misses():
    td = tempfile.mkdtemp()
    p = os.path.join(td, "instruments.json")
    _instr(p)
    got = UF.exchange_non_crypto(p)
    assert got == {"AMZUUSDT", "KODEX200USDT", "EURUSDUSDT", "XAGUSDT"}, got
    for s in got:
        assert s not in UF.NON_CRYPTO_NEW, s     # список их и правда не знает
    ref = UF.non_crypto_set(instruments_path=p)
    assert UF.is_non_crypto("AMZUUSDT", ref)
    assert not UF.is_non_crypto("BTCUSDT", ref)
    assert not UF.is_non_crypto("AEONUSDT", ref)  # innovation — крипта
    # справочник без поля: режет только список и снимок
    _instr(p, typed=False)
    assert UF.exchange_non_crypto(p) == set()
    ref0 = UF.non_crypto_set(instruments_path=p)
    assert not UF.is_non_crypto("AMZUUSDT", ref0), "контроль: без разметки AMZU проходит"
    assert UF.is_non_crypto("SHOPUSDT", ref0)     # список работает и без поля
    # битый файл — пустое множество, не исключение
    with open(p, "w") as f:
        f.write("{")
    assert UF.exchange_non_crypto(p) == set()
    print("ok  разметка площадки отсекает AMZU/KODEX200/EURUSD/XAG, крипта "
          "('' и innovation) проходит; без поля режет только список")


def test_leg_gate_uses_the_same_set():
    td = tempfile.mkdtemp()
    p = os.path.join(td, "instruments.json")
    _instr(p)
    saved = (D6._NC_REF, D6._NC_AT)
    try:
        D6._NC_REF, D6._NC_AT = (UF, UF.non_crypto_set(instruments_path=p)), 1e18
        leg = {"side": "long", "fwd": 100.0, "rr": 3.0}
        assert D6.leg_gated(dict(leg, sym="BTCUSDT"))
        assert not D6.leg_gated(dict(leg, sym="AMZUUSDT"))
        assert not D6.leg_gated(dict(leg, sym="CSOPSKHYNIX2LUSDT"))
        assert not D6.leg_gated(dict(leg, sym="METASTOCKUSDT"))
        a = D6._nc_sig()
        D6._NC_REF = (UF, UF.non_crypto_set(instruments_path=p) | {"NEWUSDT"})
        b = D6._nc_sig()
        assert a != b, "новое имя в наборе обязано менять подпись кэша ног"
    finally:
        D6._NC_REF, D6._NC_AT = saved
    print("ok  гейт ног Ladder (реплей, бумага, намерения) режет по тому же "
          "набору; новое имя меняет подпись кэша")


if __name__ == "__main__":
    for t in (test_exchange_marking_cuts_what_the_list_misses,
              test_leg_gate_uses_the_same_set):
        t()
