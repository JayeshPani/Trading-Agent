from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from app.reporting.metrics import TradeResult, max_drawdown, profit_factor, sharpe_ratio, win_rate


@dataclass(slots=True)
class EODReportGenerator:
    def generate(
        self,
        *,
        session_id: str,
        starting_capital: float,
        ending_capital: float,
        trades: list[TradeResult],
        risk_rejections: list[dict[str, Any]],
        api_errors: list[dict[str, Any]],
        open_positions: list[dict[str, Any]],
        settlement_status: dict[str, Any],
        hermes_suggestions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        pnls = [trade.pnl for trade in trades]
        wins = [trade.pnl for trade in trades if trade.pnl > 0]
        losses = [trade.pnl for trade in trades if trade.pnl < 0]
        equity_curve = [starting_capital]
        running = starting_capital
        for pnl in pnls:
            running += pnl
            equity_curve.append(running)
        return {
            "session_id": session_id,
            "starting_capital": starting_capital,
            "ending_capital": ending_capital,
            "gross_pnl": round(sum(pnls), 2),
            "net_pnl_after_charges_estimate": round(sum(pnls), 2),
            "total_trades": len(trades),
            "winning_trades": len(wins),
            "losing_trades": len(losses),
            "win_rate": win_rate(trades),
            "average_win": round(sum(wins) / len(wins), 2) if wins else 0.0,
            "average_loss": round(sum(losses) / len(losses), 2) if losses else 0.0,
            "max_drawdown": max_drawdown(equity_curve),
            "profit_factor": profit_factor(trades),
            "sharpe_ratio": sharpe_ratio(pnls),
            "best_trade": max((asdict(trade) for trade in trades), key=lambda t: t["pnl"], default=None),
            "worst_trade": min((asdict(trade) for trade in trades), key=lambda t: t["pnl"], default=None),
            "mistakes": [],
            "api_errors": api_errors,
            "risk_rejections": risk_rejections,
            "open_positions_check": {"open_positions": open_positions, "all_closed": len(open_positions) == 0},
            "settlement_withdrawal_status": settlement_status,
            "hermes_suggestions": hermes_suggestions,
        }
