import type { State } from "../../../lib/parse";
import { positionSide, leverageLabel, liqLabel } from "../../../lib/position";

export default function PositionsTable({ state }: { state: State | null }) {
  const positions = state ? Object.entries(state.positions).filter(([, p]) => p.qty !== 0) : [];
  if (positions.length === 0) return <div className="empty">Flat — no open positions.</div>;
  return (
    <table>
      <thead>
        <tr><th>Symbol</th><th>Side</th><th className="right">Qty</th><th className="right">Avg price</th><th className="right">Lev</th><th className="right">Liq. price</th><th className="right">Stop</th></tr>
      </thead>
      <tbody>
        {positions.map(([sym, p]) => (
          <tr key={sym}>
            <td>{sym}</td>
            <td>{positionSide(p.qty)}</td>
            <td className="right">{p.qty.toFixed(6)}</td>
            <td className="right">${p.avg_price.toFixed(2)}</td>
            <td className="right">{leverageLabel(p.leverage)}</td>
            <td className="right muted">{liqLabel(p.liq_price)}</td>
            <td className="right muted">${p.stop_price.toFixed(2)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
