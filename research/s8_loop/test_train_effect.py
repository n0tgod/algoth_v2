"""Замер «качество по номеру обучения»: разбор листа и агрегаты IC.

Кусается: (1) номер обучения и час читаются из головы строки листа
(строка — мегабайт, разбирать её целиком незачем), строка без номера
пропускается; (2) отчёт по IC делит оценки на «при обучении» (≥ 10
сечений, последняя на обучение) и часовые (одно сечение) по неделям;
(3) тренд: монотонный ряд даёт ρ = +1 и нуль около 0, перемешанный —
ρ около 0.
"""
import json
import os
import random
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import train_effect as TE                                     # noqa: E402


def test_hour_to_seq_reads_head_only():
    td = tempfile.mkdtemp()
    p = os.path.join(td, "sheets.jsonl")
    with open(p, "w", encoding="utf-8") as f:
        f.write(json.dumps({"hour": "2026-08-20-10", "written_at": 1.0, "train_seq": 12,
                            "arms": {"gbm": [{"sym": "AUSDT", "fwd": 1.0}] * 20000}}) + "\n")
        f.write(json.dumps({"hour": "2026-08-20-11", "written_at": 1.0, "train_seq": 12,
                            "arms": {}}) + "\n")
        f.write(json.dumps({"hour": "2026-08-20-12", "written_at": 1.0, "train_seq": None,
                            "arms": {}}) + "\n")
        f.write("битая строка\n")
    logs = []
    h2s, first = TE.hour_to_seq(p, logs.append)
    import trades as TR
    assert h2s == {int(TR._ts("2026-08-20-10")): 12, int(TR._ts("2026-08-20-11")): 12}, h2s
    assert first == {12: "2026-08-20-10"}, first
    print("ok  час → номер обучения из головы строки; без номера и битые — мимо")


def test_trend_and_null():
    rng = random.Random(1)
    seqs = list(range(1, 21))
    vals = [0.01 * s for s in seqs]                         # монотонно вверх
    groups = {h: [vals[i]] for i, h in enumerate(range(20))}
    groups["__seq__"] = {h: seqs[h] for h in range(20)}
    rho, p = TE.trend(seqs, vals, groups, rng)
    assert rho is not None and rho > 0.99 and p < 0.02, (rho, p)
    mixed = list(vals)
    rng.shuffle(mixed)
    groups2 = {h: [mixed[i]] for i, h in enumerate(range(20))}
    groups2["__seq__"] = groups["__seq__"]
    rho2, p2 = TE.trend(seqs, mixed, groups2, random.Random(2))
    assert abs(rho2) < 0.6 and p2 > 0.05, (rho2, p2)
    print(f"ok  тренд: монотонный ряд ρ={rho:+.2f} (нуль {p:.2f}), перемешанный ρ={rho2:+.2f} (нуль {p2:.2f})")


if __name__ == "__main__":
    test_hour_to_seq_reads_head_only()
    test_trend_and_null()
