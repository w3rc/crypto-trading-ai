import type { Trade } from "../../../lib/parse";

export default function TradesTable({ trades }: { trades: Trade[] }) {
  const recent = trades.slice(-30).reverse();
  if (!recent.length) return <div className="empty">No fills yet.</div>;
  return (
    <table>
      <thead>
        <tr><th>Time</th><th>Symbol</th><th>Side</th><th className="right">Qty</th><th className="right">Price</th><th className="right">Fee</th></tr>
      </thead>
      <tbody>
        {recent.map((t, i) => (
          <tr key={`${t.ts}-${i}`}>
            <td className="muted">{new Date(t.ts).toLocaleTimeString()}</td>
            <td>{t.symbol}</td>
            <td><span className={`badge ${t.side}`}>{t.side}</span></td>
            <td className="right">{t.qty.toFixed(6)}</td>
            <td className="right">${t.price.toFixed(2)}</td>
            <td className="right muted">${t.fee.toFixed(4)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
