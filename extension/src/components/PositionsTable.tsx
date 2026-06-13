import { LiveStatus } from "../api/client";

type PositionsTableProps = {
  positions: LiveStatus["open_positions"];
};

export function PositionsTable({ positions }: PositionsTableProps) {
  return (
    <section className="rounded-md border border-stone-200 bg-white">
      <div className="border-b border-stone-200 px-4 py-3">
        <h2 className="text-base font-semibold text-ink">Positions</h2>
      </div>
      <div className="max-h-52 overflow-auto">
        <table className="w-full text-left text-sm">
          <thead className="bg-panel text-xs uppercase text-stone-500">
            <tr>
              <th className="px-3 py-2">Symbol</th>
              <th className="px-3 py-2">Side</th>
              <th className="px-3 py-2">Qty</th>
              <th className="px-3 py-2">P&L</th>
            </tr>
          </thead>
          <tbody>
            {positions.length === 0 ? (
              <tr>
                <td className="px-3 py-4 text-stone-500" colSpan={4}>
                  No open positions
                </td>
              </tr>
            ) : (
              positions.map((position) => (
                <tr key={position.symbol} className="border-t border-stone-100">
                  <td className="px-3 py-2 font-medium">{position.symbol}</td>
                  <td className="px-3 py-2">{position.side}</td>
                  <td className="px-3 py-2">{position.quantity}</td>
                  <td className={position.pnl < 0 ? "px-3 py-2 text-danger" : "px-3 py-2 text-accent"}>
                    ₹{position.pnl.toFixed(2)}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}
