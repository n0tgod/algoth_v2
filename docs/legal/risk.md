# Risk Disclosure

**Read this before you connect a key or enable live trading.** It describes how you can lose money with this Service. It is not exhaustive.

## You can lose all the money in the trading account

- The strategies trade **perpetual futures with leverage**. A move against a position can liquidate it and lose the whole margin of that position; several losing positions at once can take the whole deposit.
- Some strategies **add to a losing position** (rungs). This improves the average price and also increases the size, and with it the loss, if the price keeps moving against the position.
- Short positions have no upper limit on loss.

## The record is paper, and the strategies were written by AI

- Every number in the catalog is a **paper record**: decisions replayed on recorded market data. “With backtest” includes history recomputed under today’s rules, chosen after that history was seen; “without backtest” counts only decisions written before their outcome. Neither predicts the future.
- The strategies were written and are changed by an AI research system. They have **not** been shown to have a lasting edge. A strategy can stop working, be changed or be closed.
- Rankings show past results. The best row of a table after the fact is not a forecast.

## Live is not paper

- Live prices differ from paper: slippage on entries and exits, partial fills, minimum order sizes, leverage limits of the exchange, funding payments.
- A protective stop may be rejected by the exchange (for example if it is too far from the price); our software then watches the level itself, which is slower than an exchange order.
- Delays and outages of our server, your network, or the exchange can leave a position unmanaged for some time.

## Exchange and key risks

- Your funds are held by the exchange, not by us. If the exchange fails, freezes accounts, changes rules or is unavailable in your country, you may lose access to your funds.
- Your API key gives trading access to your account. Use a key **without withdrawal or transfer rights** and **restricted to our server’s IP**; never reuse it elsewhere. Revoking the key at the exchange stops our software immediately.

## Legal and tax

- Crypto derivatives may be restricted or prohibited where you live. You are responsible for whether you may use them and for any taxes on results.

## Only trade money you can afford to lose

Start in dry-run mode, watch how a strategy behaves, start live with a small deposit, and remember that you can stop new entries or close any position at any time.
