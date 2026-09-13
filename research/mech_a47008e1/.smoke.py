"""ЧЕРНОВИК: проверка машины реплея на живых данных, НЕ результат.

Порог здесь занижен нарочно (0.5 % вместо объявленных 2 %), чтобы охрана
сработала на короткой выборке и колонки сестры посчитались. ЧИСЛА ЭТОГО
ПРОГОНА ВЕРДИКТОМ НЕ ЯВЛЯЮТСЯ и никуда не едут: вердикт считает
`guard_sister.py` на объявленном пороге. Порог 0.5 % с командной строки
не задаётся нарочно — объявленный порог читается у `path_screen.AXES`,
и занижать его можно только здесь, в черновике, который вердикта не
выносит.

Файл объявлен в `touched` отчёта постройки и потому едет в ветку: иначе
он остался бы на сервере, как `RUNBOOK.md` и `controls_check.py` у
механики 13a67a67, и следующая сессия писала бы проверку заново.

    .venv/bin/python research/mech_a47008e1/.smoke.py
"""
import resource
import sys

sys.path.insert(0, "research/mech_a47008e1")
import guard_sister as GS

print(__doc__.splitlines()[0])
s = GS.run(seeds=4, limit=900, mem_limit=1000, log=GS.log_line,
           do_replay=True, sample=60, force=True, thresh=0.5)
rep = s.get("replay") or {}
print("волна:", s.get("wave"))
print("реплей:", dict((k, rep.get(k)) for k in ("n", "why", "sum", "sample")))
print("диаг:", rep.get("diag"))
for nm, c in (("сестра", rep.get("cols")),
              ("без задержки", (rep.get("zero_lag") or {}).get("cols")),
              ("база выборки", rep.get("base"))):
    print(nm, c and dict((k, c.get(k)) for k in ("n", "usd", "usd_wo_top3d",
                                                 "final", "max_dd")))
print("beat:", rep.get("beat"))
print("убийца2:", s["killers"]["2"]["why"])
print("RSS МБ:", round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024))
