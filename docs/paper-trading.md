# Paper Trading

Paper trading is the default and the only implemented execution mode in the scaffold.

## PaperBrokerAdapter Behavior

- Simulates limit orders.
- Rejects market orders.
- Tracks cash.
- Tracks long positions.
- Allows `SELL` only to close an existing long paper position.
- Supports square-off of open paper positions.
- Never calls Breeze.

## Strategy Scope

Initial strategy scaffolds:

- VWAP trend.
- Moving average crossover.
- Breakout with volume confirmation.
- RSI mean reversion, paper-only.
- Opening range breakout, paper-only.

Strategies emit complete signal fields: symbol, action, confidence, entry, stop, target, risk/reward, invalidation reason, timeframe, and explanation.
