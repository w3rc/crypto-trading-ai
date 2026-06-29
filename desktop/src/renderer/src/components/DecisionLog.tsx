import type { Decision } from "../../../lib/parse";

export default function DecisionLog({ decisions }: { decisions: Decision[] }) {
  const recent = decisions.slice(-30).reverse();
  if (!recent.length) return <div className="empty">No decisions logged yet.</div>;
  return (
    <table>
      <thead>
        <tr><th>Time</th><th>Symbol</th><th>Action</th><th>Price</th><th>Status</th><th>Reason</th></tr>
      </thead>
      <tbody>
        {recent.map((d) => (
          <tr key={`${d.ts}-${d.symbol}`}>
            <td className="muted">{new Date(d.ts).toLocaleTimeString()}</td>
            <td>{d.symbol}</td>
            <td><span className={`badge ${d.action}`}>{d.action}</span></td>
            <td>${d.price.toFixed(2)}</td>
            <td>{d.executed
              ? <span className="exec-yes">✓ done</span>
              : <span className="exec-no">skipped</span>}</td>
            <td className="muted">{d.reason}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
