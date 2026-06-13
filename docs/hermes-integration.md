# Hermes Integration

Hermes is a research and improvement layer, not an execution engine.

## Allowed

- Read trade logs.
- Read EOD reports.
- Review failed trades and API errors.
- Identify bad signals.
- Suggest strategy changes.
- Generate backtesting experiments.
- Improve prompts and evaluation rubrics.
- Create coding tasks or GitHub issues.
- Compare old and new strategies.

## Blocked

- Place real trades.
- Override risk decisions.
- Modify live strategy without approval.
- Access broker credentials.
- Withdraw money.
- Click ICICI Direct DOM.
- Store OTPs or passwords.

## Promotion Flow

1. Collect historical data.
2. Run backtests.
3. Run paper trades.
4. Store all signals, orders, trades, errors, and results.
5. Hermes reviews the logs.
6. Hermes suggests improvements.
7. System tests improvements offline.
8. Passing changes become candidates.
9. User approval is required.
10. Live trading remains limited by the risk engine.
