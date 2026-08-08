#!/usr/bin/env python3
"""
Семейства признаков — вид СИТУАЦИИ словами трейдера, и объяснение
каждого простыми словами. Единственное определение на весь проект.

Почему отдельным модулем, а не внутри `bookfeat.py`, где карта жила
раньше: справочник читает её ВЕБ-СЕРВЕР, а `bookfeat` тянет numpy и
математику M1. Копировать карту в сборщик запрещено правилами проекта
(две таблицы, решающие одно, однажды разойдутся — этим кончились
`nulls.py` в F3 и загрузчик funding). Здесь только стандартная
библиотека, и `bookfeat` берёт карту отсюда же — то есть источник
по-прежнему один, просто он лёгкий.

Чего этот файл НЕ утверждает: что у модели есть дискретные стратегии.
Модель одна на все ситуации, и семейство сделки — это чтение вкладов
(`contrib`) в ОДИН прогноз, а не выбранное правило. Справочник даёт
словарь, на котором модель вообще способна думать, и страница обязана
подписывать его именно так.
"""

FAMILY_EXACT = {
    "imb_best": "book", "spread_rel": "book", "upd_rel": "book",
    "delta": "tape", "turn_rel": "tape", "burst": "tape",
    "traded_share": "tape",
    "eat_bid": "absorption", "eat_ask": "absorption",
    "big_rel": "absorption",
    "fr_bp": "funding", "mins_fund": "funding", "basis_bp": "funding",
    "net_path_24h": "move", "vol_regime": "vol",
    "range_pos": "range", "dwell_24h": "range",
    "dist_round": "round", "beta": "beta", "age_rec": "age",
    "dow": "clock",
    "btc_ret_4h": "leader", "sec_ret_4h": "leader",
    # Отставание от своего сектора (ход минус ход сектора) — тоже
    # семейство лидера: признак про «свои уже ушли», а не про сам ход.
    # Найден ТЕСТОМ на полноту карты, а не чтением, — ровно для этого
    # тест и заведён.
    "rel_sec_4h": "leader",
}
FAMILY_PREFIX = (
    ("imb_", "book"), ("depth_b", "book"), ("depth_a", "book"),
    ("liq_", "liq"), ("oi_", "oi"), ("ret_", "move"),
    ("squeeze_", "squeeze"), ("tilt_", "tilt"), ("hod_", "clock"),
)


def family(name):
    """Семейство признака; незнакомое имя — «other», и тест на живом
    списке признаков обязан держать «other» пустым."""
    got = FAMILY_EXACT.get(name)
    if got:
        return got
    for pre, fam in FAMILY_PREFIX:
        if name.startswith(pre):
            return fam
    return "other"


# Порядок — как читает трейдер: сперва то, что видно в стакане и ленте,
# потом производные рынка, потом контекст. Страница печатает его как
# есть, своего порядка не выдумывает.
#
# `plain` пишется для владельца: он трейдер, не программист, и обязан
# мочь оспорить каждое утверждение. `caveat` не украшение — это то, чего
# семейство НЕ значит, и без него справочник читался бы как обещание.
GLOSSARY = (
    ("absorption", {
        "title": "Absorption — the book being eaten",
        "plain": "Someone keeps putting size back at the same price "
                 "while the market keeps hitting it. The wall does not "
                 "move and the price does not go through it. This is "
                 "the one thing the tape alone could never show: the "
                 "tape gives how much was traded, the book gives how "
                 "much was shown, and absorption is the ratio of the "
                 "two — more traded than was ever displayed means the "
                 "level was being refilled by hand.",
        "reads": "aggressive volume of the hour against the depth "
                 "actually displayed on the opposite side, plus the "
                 "size of the largest resting order vs what is normal "
                 "for this coin",
        "caveat": "Measured on prints alone (T1–T4) this carried no "
                  "direction at all — four probes, all zero. It is in "
                  "the model because the book half of the ratio was "
                  "never available before B1, not because it is "
                  "proven.",
    }),
    ("book", {
        "title": "Order book — imbalance and depth",
        "plain": "How lopsided the book is: how much is resting on "
                 "the bid against the ask, near the price and further "
                 "out, and whether that depth is thicker or thinner "
                 "than this coin usually shows. A thin book on one "
                 "side means the same order moves price further.",
        "reads": "bid vs ask size at the top and inside ±0.05…0.5 % "
                 "bands, each band against its own past; the spread "
                 "and how fast the book is being rewritten",
        "caveat": "The bands are only as wide as the feed reaches. On "
                  "BTC 200 levels span about 4 basis points, so the "
                  "narrow bands there measure nothing and the model "
                  "sees them as missing, not as zero.",
    }),
    ("tape", {
        "title": "Tape pressure — who is hitting harder",
        "plain": "The flow of actual trades: whether buyers or "
                 "sellers are the ones crossing the spread, how much "
                 "turnover the hour had against its usual, and "
                 "whether it came as one burst or was spread evenly. "
                 "A burst is somebody in a hurry.",
        "reads": "buy minus sell aggressive volume, turnover vs its "
                 "own past, the biggest one-second spike, and how "
                 "much of the hour had any trade at all",
        "caveat": "An hour with almost no trades is not a quiet "
                  "market, it is a stale price — which is why the "
                  "traded share is a feature and not a filter.",
    }),
    ("liq", {
        "title": "Liquidations — positions being closed by force",
        "plain": "Forced closures, not decisions. When a cascade "
                 "runs, positions do not get reopened — they "
                 "disappear, and price moves because someone had to "
                 "trade, not because someone wanted to. The model "
                 "sees which side is being carried out and how big "
                 "that is against the hour's ordinary turnover.",
        "reads": "long and short liquidations as a share of turnover, "
                 "and the imbalance between the two sides",
        "caveat": "The rebound after a cascade was measured directly "
                  "(L1–L3) and, against the cross-section of "
                  "everything falling at the same minute, it was "
                  "worth 4–11 bp against a round trip of 11.7 — the "
                  "market's rebound, not the coin's.",
    }),
    ("oi", {
        "title": "Open interest — how crowded the trade is",
        "plain": "How much money is standing in this contract right "
                 "now, against its usual level, and whether the crowd "
                 "has been arriving or leaving over the last hours "
                 "and day. Open interest falling while price moves is "
                 "the fingerprint of positions being closed rather "
                 "than opened.",
        "reads": "open interest vs its own past week, plus its change "
                 "over 4 h and 24 h",
        "caveat": "Binance publishes the reading five minutes late, "
                  "and that lateness is built into how the feature is "
                  "dated. Reading it as of its own timestamp was "
                  "looking into the future, and was measured to be so.",
    }),
    ("funding", {
        "title": "Funding and basis — what the position costs to hold",
        "plain": "The perpetual pays one side and charges the other "
                 "every few hours. A large positive rate means the "
                 "longs are paying — the crowd is long. The basis is "
                 "the same fact seen from the price: how far the perp "
                 "trades from spot.",
        "reads": "current funding rate, minutes to the next payment, "
                 "and perp premium or discount to spot",
        "caveat": "Funding as a strategy of its own was tested and "
                  "closed (hypothesis 3): the carry is real, but the "
                  "book that collects it shorts exactly the crowded "
                  "longs that produce squeezes, and the drawdown was "
                  "worse than a random book's.",
    }),
    ("squeeze", {
        "title": "Squeeze — the range compressing",
        "plain": "Price is doing less than it usually does: the high "
                 "to low of the last hours is unusually narrow for "
                 "this coin. Traders read compression as a spring — "
                 "the market goes quiet before it does not.",
        "reads": "the 4 h and 24 h range, each divided by what that "
                 "coin's range normally is",
        "caveat": "A number, not a rule. T3/T4 measured entries at "
                  "levels WITHOUT any compression condition and the "
                  "outcomes fell on a random walk; compression as a "
                  "condition is untested, which is exactly why it is "
                  "a feature the model may or may not use.",
    }),
    ("tilt", {
        "title": "Tilt — a one-sided drift inside the range",
        "plain": "The move is not a spike and not a chop: over the "
                 "window price has quietly netted most of its own "
                 "range in one direction. The sign says which way it "
                 "leans, the size says how cleanly.",
        "reads": "net 4 h move divided by the 4 h range",
        "caveat": "Close relatives of this — how straight the move "
                  "was — sit in the move family, and the two can "
                  "carry the same information twice.",
    }),
    ("range", {
        "title": "Range and dwell — where price sits and how long",
        "plain": "Two plain questions: is price at the top of its "
                 "day, at the bottom, or in the middle; and how much "
                 "of the last day did it spend inside the corridor it "
                 "is in now. Long dwell is accumulation in a trader's "
                 "language — time at a price, not volume at a price.",
        "reads": "position inside the 24 h range (0 low, 1 high), and "
                 "the share of the last 24 hourly closes that fell "
                 "inside the current 4 h corridor",
        "caveat": "Dwell is time, not size. Volume at price is a "
                  "different question, and it is answered by the "
                  "absorption family.",
    }),
    ("move", {
        "title": "The coin's own move — and how straight it was",
        "plain": "How far the coin has gone over the last hour, four "
                 "hours, day — always measured in units of its own "
                 "volatility, so that a 3 % move in a quiet coin and "
                 "in a wild one are not called the same thing. Plus "
                 "whether it walked there in a straight line or "
                 "wandered.",
        "reads": "1 h, 4 h and 24 h returns normalised by the coin's "
                 "own volatility, and net move divided by path walked",
        "caveat": "This is the family that already worked once: "
                  "short-term reversal was the strongest single "
                  "feature the project ever measured (IC 0.047), and "
                  "the whole point of the model is to beat it, not to "
                  "rediscover it.",
    }),
    ("vol", {
        "title": "Volatility regime — awake or asleep",
        "plain": "Whether this coin is currently moving more or less "
                 "than it has been over the week. The same signal "
                 "means different money in a sleeping market and in a "
                 "screaming one, and this is what tells the model "
                 "which it is in.",
        "reads": "today's volatility divided by the week's",
        "caveat": None,
    }),
    ("leader", {
        "title": "Leader and sector — is the coin late",
        "plain": "What BTC did in the last four hours, what this "
                 "coin's own sector did, and how far the coin is "
                 "behind its sector. A coin that has not moved while "
                 "its neighbours already have is a different animal "
                 "from one that led them.",
        "reads": "BTC's 4 h move, the sector's 4 h move excluding the "
                 "coin itself, and the difference between the coin "
                 "and its sector",
        "caveat": "The sector average excludes the coin, for the same "
                  "reason the market wave does: including yourself in "
                  "the thing you are compared against inflates the "
                  "comparison, and that bias was measured, not assumed.",
    }),
    ("beta", {
        "title": "Beta — how hard the coin follows the market",
        "plain": "When the whole market moves one percent, how much "
                 "does this coin usually move. It is not a signal on "
                 "its own — it is what lets the model tell the coin's "
                 "own move apart from the market carrying everything "
                 "along.",
        "reads": "rolling regression of the coin against the market "
                 "wave built without the coin itself",
        "caveat": "The forecast the model trades is the residual "
                  "AFTER the wave is subtracted with this beta. If "
                  "beta is wrong, the model is trading the market and "
                  "calling it the coin.",
    }),
    ("round", {
        "title": "Round levels",
        "plain": "How close price is to a round number, on a scale "
                 "that fits the coin: 1 000 for BTC at ninety "
                 "thousand, 0.001 for a coin at five cents. Orders "
                 "pile up on round numbers because people put them "
                 "there.",
        "reads": "distance to the nearest round price, as a share of "
                 "the round grid step",
        "caveat": "Structural levels built out of the daily volume "
                  "profile were measured in T4 and did not carry "
                  "direction; roundness alone is a weaker claim than "
                  "that one was.",
    }),
    ("clock", {
        "title": "Time of day and day of week",
        "plain": "Crypto trades around the clock, but the people do "
                 "not. Asian morning, London open and the American "
                 "afternoon are different markets, and so is the "
                 "weekend.",
        "reads": "hour of day as a circle (so 23:00 and 00:00 are "
                 "neighbours, not opposite ends) and day of week",
        "caveat": "A seasonality feature is the easiest way to overfit "
                  "a short history: with a few months recorded, every "
                  "hour of the day has been seen only a few dozen "
                  "times.",
    }),
    ("age", {
        "title": "Listing age",
        "plain": "How long the coin has existed in the record. Young "
                 "listings behave differently — in the daily model "
                 "this was the strongest single feature on the five "
                 "day horizon: young coins lag the wave.",
        "reads": "hours since the first recorded hour for this coin",
        "caveat": "Censored by when recording started, not by the real "
                  "listing date — every coin present at the start ages "
                  "at the same rate, which is a property of our record "
                  "and not of the market.",
    }),
    ("other", {
        "title": "Unmapped",
        "plain": "A feature the model trains on that has no family "
                 "written for it. This list must be empty: a new "
                 "feature without a line in the map would quietly "
                 "dilute every situation name on every page.",
        "reads": "nothing — this is a defect indicator",
        "caveat": None,
    }),
)

GLOSSARY_BY_KEY = dict(GLOSSARY)
