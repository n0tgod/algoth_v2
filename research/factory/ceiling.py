"""Потолок заявки: стоит ли её вообще объявлять.

Шаг стоит между заявкой предлагающего и её объявлением и отвечает на
один вопрос — **можно ли эту заявку измерить**. Самые дешёвые закрытия
в проекте были расчётами, сделанными ДО постройки: потолок трёх рычагов
S1 закрыл направление за вечер, мейкерский потолок R5 сэкономил недели,
замер пассивного входа D1 закрыл последний рычаг гипотезы 7.

Потолок судит заявку СТРУКТУРНО и ровно по двум величинам.

* **Измеримость.** Сколько сделок кандидат делает за сутки ЗАПИСИ.
  Ячейка, дающая единицы сделок, мертва по построению: её нельзя
  рассудить ни за девяносто суток, ни за какие — правило вылета судит
  окно в `pool.WINDOW_D` суток, и в окно обязано попадать хоть что-то.
  Знаменателем служит длина записи, и никак иначе: живой писатель
  заводит день в дневном ряду только от ЗАКРЫТОЙ сделки
  (`candidate.daily_net`), поэтому суток у книги никогда не больше, чем
  сделок, и отношение «сделок в сутки», посчитанное по её собственным
  дням, не падает ниже единицы ни при какой тонкости книги — ворота не
  связывали бы вовсе. Длину записи кладёт в артефакт `run_day`; её
  отсутствие есть `undetermined`, а не молчаливый откат к суткам книг.
* **Независимость.** Насколько дневные деньги повторяют деньги уже
  живого кандидата. Пул мерит информацию эффективным `N`, и новичок,
  идущий с живым в ногу, наблюдений не добавляет, сколько бы их ни было
  номинально.

**Чего потолок не делает никогда: он не судит по доходности.** Отбирая
по прошлому, мы объявляли бы только то, что уже выглядело хорошо на
записи, и вердикт вперёд терял бы смысл — это ошибка R5 в чистом виде,
стоившая проекту месяца. Ни нетто заявки, ни его знак, ни его величина
не участвуют ни в одной ветке расчёта; закреплено двумя тестами —
переворот знака всех дневных денег и умножение их на положительное
число вердикта не меняют.

Чего потолок НЕ закрывает, и это сказано, чтобы не читалось шире:
книга-зеркало (связь около −1) им не закрывается. Пул считает
информацию положительной связью (отрицательная подрезается нулём в
`ledger.effective_n`), то есть зеркало для знаменателя — полноценное
испытание, и потолок обязан мерить ту же величину, которой мерит пул.

Модуль на стандартной библиотеке: он читает АРТЕФАКТ суточного прогона,
а не хранилище. Второй проход по барам был бы стократной платой за то
же число, а второй расчёт связи разошёлся бы с тем, которым фабрика
считает своё эффективное `N`.
"""

import argparse
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)
ROOT = os.path.dirname(RESEARCH)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import ledger as LG                                          # noqa: E402
import pool as PL                                            # noqa: E402
import space as SP                                           # noqa: E402

OUT = os.path.join(HERE, "out")
JOURNAL = "ceilings.jsonl"

PASS = "pass"
CLOSED = "closed"
UNDET = "undetermined"

# --- пороги. Объявлены ДО расчёта и после него не смягчаются ----------
#
# Минимум сделок задан СКОРОСТЬЮ, а не абсолютным числом. Правило вылета
# судит книгу окном в `PL.WINDOW_D` суток по сумме нетто окна; при
# горстке сделок знак этой суммы есть подбрасывание монеты, а не
# измерение, и десять сделок в окне — низший порядок, при котором о
# сумме вообще есть что сказать. Отсюда скорость; требуемое число
# выводится из длины записи, а не стоит литералом — иначе один и тот же
# порог означал бы разное на записи в неделю и на записи в год.
MIN_TRADES_IN_WINDOW = 10
MIN_TRADES_PER_DAY = MIN_TRADES_IN_WINDOW / float(PL.WINDOW_D)

# Предел связи. При связи 0.95 пара книг несёт эффективное
# `N = 2 / (1 + 0.95) = 1.03`: второй кандидат добавляет три сотых
# наблюдения и тратит целое испытание. Формула не копируется —
# эффективное `N` пары считает `ledger.effective_n`, тот же код, каким
# фабрика печатает своё `N` в отчёте.
MAX_CORR = 0.95

# Столько же общих суток, сколько требует `ledger.effective_n`: пара,
# которую пул не берёт в свой знаменатель, и потолком не измеряется.
MIN_PAIR_DAYS = 3


# --- чтение артефакта -------------------------------------------------

def read_run(path):
    """Артефакт суточного прогона или причина, по которой его нет.

    Причина возвращается СЛОВАМИ, а не пустым словарём: «прогона ещё не
    было» и «прогон сломан» лечатся по-разному, и потолок не вправе
    сводить их в одно молчание.
    """
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except OSError as e:
        return None, f"суточного прогона нет ({path}): {e.strerror}"
    except ValueError as e:
        return None, f"артефакт прогона не разбирается ({path}): {e}"
    if not isinstance(data, dict):
        return None, f"артефакт прогона не объект ({path})"
    return data, None


def _days(obj):
    """Дневной ряд из артефакта: ключ дня — ЧИСЛО, а не строка.

    День в этом проекте всюду номер суток: его кладёт числом
    `candidate.daily_net`, арифметически сравнивает `pool.window_net`,
    JSON по дороге превращает в текст. Читатель обязан вернуть тот же
    тип, потому что строки сравниваются как текст: `'998' > '1000'`, и
    первая же величина, посчитанная по окну дней, посчиталась бы по
    алфавиту.

    Прежний довод («ряд со строковыми ключами не пересечётся с рядом
    соседа») был неверен и убран: обе стороны пары читаются из ОДНОГО
    артефакта, и как строки они пересекаются ровно так же. Сегодня ни
    одна ветка потолка от порядка дней не зависит — правило держится
    ради типа, а не ради связи, и закреплено проверкой на порядке.
    """
    out = {}
    if not isinstance(obj, dict):
        return out
    for k, v in obj.items():
        try:
            out[int(k)] = float(v)
        except (TypeError, ValueError):
            continue
    return out


def record_days(run):
    """Длина ЗАПИСИ в сутках из артефакта — знаменатель измеримости.

    Кладёт её `run_day` по журналу листов сечения, до отсева ног
    гейтами. Здесь она только читается: считать её по книгам прогона
    нельзя (см. шапку модуля), а считать самому — значило бы завести в
    потолке вторую реализацию того же числа.

    Отсутствие поля — `None`, то есть «не измерено», а не «столько,
    сколько нашлось»: артефакт прежнего образца длины записи не несёт, и
    молчаливый откат к суткам книг вернул бы ровно тот дефект, ради
    которого поле заведено.
    """
    meta = run.get("meta") if isinstance(run, dict) else None
    v = meta.get("record_days") if isinstance(meta, dict) else None
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return int(v) if v >= 0 else None


# --- связь ------------------------------------------------------------

def pair_corr(a, b, min_days=MIN_PAIR_DAYS):
    """Связь дневных денег двух книг по ОБЩИМ суткам.

    Возвращает (связь или None, число общих суток). `None` означает
    «не измерено» и печатается прочерком: ноль здесь читался бы как
    «измерено и книги независимы», то есть как разрешение объявлять.

    Сама связь считается `ledger._corr` — тем же кодом, которым фабрика
    считает эффективное `N`. Вторая реализация формулы однажды разошлась
    бы с первой, и потолок закрывал бы кандидатов, которых пул считает
    независимыми (двумя копиями формулы в этом проекте уже кончались
    `nulls.py` и загрузчик funding).
    """
    days = sorted(set(a) & set(b))
    if len(days) < min_days:
        return None, len(days)
    return LG._corr([a[d] for d in days], [b[d] for d in days]), len(days)


def pair_eff_n(a, b):
    """Эффективное `N` пары книг — тем же `effective_n`, что у отчёта."""
    n_eff, _r = LG.effective_n({"pending": a, "live": b})
    return n_eff


# --- вердикт ----------------------------------------------------------

def _res(verdict, why, **kw):
    out = {"verdict": verdict, "why": why}
    out.update(kw)
    return out


def judge(run, min_tpd=MIN_TRADES_PER_DAY, max_corr=MAX_CORR,
          min_pair_days=MIN_PAIR_DAYS):
    """Вердикт потолка по артефакту суточного прогона.

    Одно из трёх: `pass` — объявлять можно; `closed` — закрыто с
    причиной ЧИСЛОМ; `undetermined` — посчитать нечем. Последнее не есть
    `pass`: кандидат ждёт, а не проходит по умолчанию.

    Фразы вердикта собираются из посчитанных величин, а не стоят рядом
    с ними литералом: проза, утверждающая своё, однажды разойдётся со
    своей же таблицей — это уже случалось в отчёте о цене прохода
    лесенки.
    """
    if not isinstance(run, dict):
        return _res(UNDET, "артефакта суточного прогона нет вовсе")
    pend = run.get("pending")
    if not isinstance(pend, dict) or not isinstance(pend.get("rule"), dict):
        why = run.get("pending_why") or "поля заявки в артефакте нет"
        return _res(UNDET, f"заявки в прогоне нет: {why}")
    key = pend.get("key") or SP.key(pend["rule"])
    rule = pend["rule"]
    cands = run.get("candidates") or {}
    live = {cid: _days(c.get("daily")) for cid, c in cands.items()
            if cid != key}
    p_daily = _days(pend.get("daily"))
    n_days = record_days(run)
    base = {"id": key, "rule": rule, "days": n_days,
            "pending_days": len(p_daily),
            "trades": pend.get("trades"),
            "min_trades_per_day": round(min_tpd, 3),
            "min_pair_days": min_pair_days,
            "max_corr": max_corr}
    if n_days is None:
        return _res(UNDET,
                    "длины записи в артефакте нет (`meta.record_days`) — "
                    "артефакт прежнего образца. Считать измеримость по "
                    "суткам самих книг нельзя: живой писатель заводит "
                    "день только от закрытой сделки, суток у книги "
                    "никогда не больше, чем сделок, и ворота не "
                    "связывали бы вовсе", **base)
    if n_days == 0:
        return _res(UNDET, "в записи нет ни одних суток — "
                    "считать не по чему", **base)
    p_tr = pend.get("trades")
    if not isinstance(p_tr, int):
        return _res(UNDET, "у заявки в артефакте нет числа сделок", **base)
    live_tr = sum(c.get("trades") or 0 for c in cands.values()
                  if isinstance(c, dict))
    if p_tr == 0 and live_tr == 0:
        # Ноль сделок У ВСЕХ книг прогона означает сломанный реплей, а
        # не мёртвую заявку. Пустота не вправе выдавать себя за вердикт
        # — тем же правилом суточный прогон отказывает при нуле исходов.
        return _res(UNDET, f"ни у одной книги прогона нет сделок "
                    f"({len(cands)} живых) — сломан реплей, а не заявка "
                    f"мертва", **base)
    need = min_tpd * n_days
    rate = p_tr / float(n_days)
    base["need_trades"] = round(need, 1)
    base["per_day"] = round(rate, 3)
    if p_tr < need:
        # Всё, чем закрывает эта ветка, выводится из ДВУХ посчитанных
        # чисел — скорости и порога, по которому принято решение.
        # Литерал `MIN_TRADES_IN_WINDOW` стоял здесь и опровергал
        # собственный вывод: при пороге 50 в сутки фраза говорила «это
        # 100.0 сделки при 10, то есть подбрасывание монеты».
        return _res(CLOSED,
                    f"измеримости нет: {p_tr} сделок за {n_days} суток "
                    f"записи — {rate:.2f} в сутки при требуемых "
                    f"{min_tpd:.2f}; в окне вылета в {PL.WINDOW_D} суток "
                    f"это {rate * PL.WINDOW_D:.1f} сделки при требуемых "
                    f"{min_tpd * PL.WINDOW_D:.1f}, то есть подбрасывание "
                    f"монеты, а не измерение", **base)
    links = []
    for cid in sorted(live):
        r, k = pair_corr(p_daily, live[cid], min_pair_days)
        links.append({"id": cid, "r": None if r is None else round(r, 4),
                      "days": k})
    base["links"] = links
    if not links:
        return _res(PASS, f"объявлять можно: сделок {p_tr} за {n_days} "
                    f"суток записи ({rate:.2f} в сутки при требуемых "
                    f"{min_tpd:.2f}); живых книг в пуле нет вовсе, "
                    f"повторять нечего — связь остаётся прочерком",
                    **base)
    measured = [lk for lk in links if lk["r"] is not None]
    if not measured:
        return _res(UNDET,
                    f"связь не измерима ни с одной из {len(links)} живых "
                    f"книг: общих суток меньше {min_pair_days} — "
                    f"кандидат ждёт, а не проходит по умолчанию", **base)
    best = max(measured, key=lambda lk: lk["r"])
    base["closest"] = best
    base["pair_eff_n"] = round(pair_eff_n(p_daily, live[best["id"]]), 3)
    # Связь ЗНАКОВАЯ, без модуля, и это решение, а не описка: пул
    # считает информацию положительной связью — отрицательная
    # подрезается нулём в `ledger.effective_n`, — то есть книга-зеркало
    # для знаменателя полноценное испытание, и потолок обязан мерить ту
    # же величину, которой мерит пул. Держалось одной прозой и потому
    # переворачивалось бы молча; закреплено проверкой на зеркале.
    if best["r"] >= max_corr:
        return _res(CLOSED,
                    f"независимости нет: дневные деньги повторяют "
                    f"`{best['id']}` со связью {best['r']:+.3f} при "
                    f"пределе {max_corr:.2f} по {best['days']} общим "
                    f"суткам — пара несёт эффективное N "
                    f"{base['pair_eff_n']:.2f} вместо двух, то есть "
                    f"испытание тратится, а наблюдений не прибавляется",
                    **base)
    return _res(PASS,
                f"объявлять можно: {p_tr} сделок за {n_days} суток записи "
                f"({rate:.2f} в сутки при требуемых {min_tpd:.2f}), "
                f"теснейшая связь {best['r']:+.3f} с `{best['id']}` при "
                f"пределе {max_corr:.2f} — пара несёт эффективное N "
                f"{base['pair_eff_n']:.2f}", **base)


# --- журнал закрытых потолком ----------------------------------------

def journal_path(base=None):
    return os.path.join(base or OUT, JOURNAL)


def read_journal(base=None):
    """События потолка и число НЕразобранных строк — как у реестра."""
    rows, bad = [], 0
    try:
        with open(journal_path(base), encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except ValueError:
                    bad += 1
                    continue
                if isinstance(r, dict) and r.get("id"):
                    rows.append(r)
                else:
                    bad += 1
    except OSError:
        return [], 0
    return rows, bad


def record(res, at=None, base=None):
    """Дописать вердикт в журнал потолка. Причина отказа или None.

    Журнал отдельный от реестра объявлений намеренно: закрытая потолком
    заявка испытанием НЕ стала и знаменатель доказательства не тратит,
    а лежи она в одном журнале с объявленными — считалась бы вместе с
    ними.

    Пишутся ВСЕ вердикты, а не одни закрытия: журнал, хранящий только
    закрытых, прячет собственный знаменатель потолка — сколько заявок он
    пропустил. Дозапись идёт при СМЕНЕ вердикта: суточный прогон зовёт
    потолок каждый день, и строка на каждый вызов сделала бы журнал
    записью расписания, а не решений.
    """
    cid = res.get("id")
    if not cid:
        return "у вердикта нет ключа заявки — писать нечего"
    rows, _bad = read_journal(base)
    prev = [r for r in rows if r.get("id") == cid]
    if prev and prev[-1].get("verdict") == res["verdict"]:
        return (f"вердикт {res['verdict']} по {cid} уже записан — "
                f"строка на каждый вызов сделала бы журнал расписанием")
    row = {"at": round(at if at is not None else time.time(), 1),
           "id": cid, "verdict": res["verdict"], "why": res.get("why"),
           "rule": res.get("rule"), "trades": res.get("trades"),
           "days": res.get("days"), "closest": res.get("closest")}
    p = journal_path(base)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return None


# --- отчёт ------------------------------------------------------------

def _num(x, fmt="{:+.3f}"):
    """Величина, которой НЕТ, — прочерк, а не ноль: ноль означает
    «измерено и равно нулю»."""
    return "—" if x is None else fmt.format(x)


def write_report(path, res, log=print):
    L = []
    cid = res.get("id")
    L.append(f"# Потолок заявки{'' if not cid else ' — `' + cid + '`'}\n")
    if res.get("rule"):
        L.append(SP.describe(res["rule"]) + "\n")
    L.append(f"**{res['verdict']}: {res['why']}**\n")
    L.append("## Числа\n")
    L.append("| величина | число |")
    L.append("|---|--:|")
    L.append(f"| суток записи | {_num(res.get('days'), '{:d}')} |")
    L.append(f"| из них суток со сделками у заявки | "
             f"{_num(res.get('pending_days'), '{:d}')} |")
    L.append(f"| сделок заявки | {_num(res.get('trades'), '{:d}')} |")
    L.append(f"| сделок в сутки | {_num(res.get('per_day'), '{:.2f}')} |")
    L.append(f"| требуется в сутки | "
             f"{_num(res.get('min_trades_per_day'), '{:.2f}')} |")
    cl = res.get("closest") or {}
    L.append(f"| теснейшая связь с живой книгой | "
             f"{_num(cl.get('r'))} |")
    L.append(f"| с какой книгой | {cl.get('id') or '—'} |")
    L.append(f"| общих суток у этой пары | "
             f"{_num(cl.get('days'), '{:d}')} |")
    L.append(f"| эффективное N этой пары | "
             f"{_num(res.get('pair_eff_n'), '{:.2f}')} |")
    L.append(f"| предел связи | "
             f"{_num(res.get('max_corr'), '{:.2f}')} |")
    L.append("")
    L.append("Прочерк в таблице означает, что расчёт до этой величины не "
             "дошёл, — а не что величина равна нулю: ноль здесь читался "
             "бы как «измерено», то есть как разрешение объявлять.\n")
    if res.get("links"):
        L.append("## Связь с каждой живой книгой\n")
        L.append("| книга | связь | общих суток |")
        L.append("|---|--:|--:|")
        for lk in res["links"]:
            L.append(f"| `{lk['id']}` | {_num(lk.get('r'))} | "
                     f"{lk.get('days')} |")
        L.append("")
        # Порог берётся из САМОГО вердикта, а не из константы модуля:
        # решать могли другим числом (потолок зовут с порогом
        # аргументом), и константа в отчёте противоречила бы строке
        # вердикта в том же файле — это уже случалось.
        L.append("Прочерк означает «не измерено», а не «связи нет»: "
                 "общих суток у пары меньше "
                 f"{_num(res.get('min_pair_days'), '{:d}')}, и пул такую "
                 "пару в свой знаменатель тоже не берёт.\n")
    L.append("## По доходности заявка НЕ судилась\n")
    L.append("Ни нетто заявки, ни его знак, ни его величина не участвуют "
             "ни в одной ветке расчёта выше — в артефакт они попадают, "
             "но потолок их не читает. Отбирая по прошлому, мы объявляли "
             "бы только то, что уже выглядело хорошо на записи, и "
             "вердикт вперёд терял бы смысл: это ошибка R5, стоившая "
             "проекту месяца. Закреплено двумя тестами — переворот знака "
             "всех дневных денег и умножение их на положительное число "
             "вердикта не меняют.\n")
    L.append("Чего потолок не закрывает: книгу-зеркало (связь около "
             "−1). Пул считает информацию положительной связью — "
             "отрицательная подрезается нулём в `ledger.effective_n`, — "
             "и потолок обязан мерить ту же величину, которой мерит "
             "пул.\n")
    L.append("Ретро-прогон, из которого взяты числа, вердиктом о рынке "
             "НЕ является: потолок отвечает только на вопрос, можно ли "
             "заявку измерить.\n")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(L))
    log(f"отчёт: {path}")
    return path


def publish(log=print):
    """Публикация — часть прогона, а не отдельный шаг: шаг, который
    можно забыть, рано или поздно забывают (урок D1)."""
    try:
        subprocess.run([os.path.join(ROOT, "tools", "publish.sh"),
                        "фабрика: потолок заявки"],
                       cwd=ROOT, check=False, timeout=600)
    except Exception as e:                                # noqa: BLE001
        log(f"публикация не удалась: {type(e).__name__}: {e}")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--base", default=None,
                    help="каталог журнала потолка (по умолчанию --out)")
    ap.add_argument("--tag", default="1m")
    ap.add_argument("--run", default=None,
                    help="артефакт суточного прогона")
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args(argv)
    log = print
    run_path = a.run or os.path.join(a.out, f"factory-day-{a.tag}.json")
    base = a.base or a.out
    run, why = read_run(run_path)
    res = (_res(UNDET, why) if run is None else judge(run))
    log(f"{res['verdict']}: {res['why']}")
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "ceiling.json"), "w",
              encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    write_report(os.path.join(a.out, f"CEILING-{a.tag}.md"), res, log=log)
    if res.get("id"):
        skipped = record(res, base=base)
        if skipped:
            log(skipped)
    if not a.no_publish:
        publish(log=log)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
