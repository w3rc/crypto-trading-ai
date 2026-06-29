import type { Decision } from "../../../lib/parse";

type Row = Decision & { count: number };

// Collapse CONSECUTIVE non-executed rows with an identical reason into one row
// carrying a ×N count. Executed trades always stay their own row.
function collapse(items: Decision[]): Row[] {
  const out: Row[] = [];
  for (const d of items) {
    const prev = out[out.length - 1];
    if (prev && !prev.executed && !d.executed && prev.reason === d.reason) {
      prev.count += 1;
    } else {
      out.push({ ...d, count: 1 });
    }
  }
  return out;
}

function short(reason: string): string {
  return reason.length > 80 ? reason.slice(0, 79) + "…" : reason;
}

export default function DecisionLog({ decisions }: { decisions: Decision[] }) {
  const rows = collapse(decisions.slice(-50)).slice(-30).reverse();
  if (!rows.length) return <div className="empty">No decisions logged yet.</div>;
  return (
    <table>
      <thead>
        <tr><th>Time</th><th>Symbol</th><th>Action</th><th>Price</th><th>Status</th><th>Reason</th></tr>
      </thead>
      <tbody>
        {rows.map((d, i) => (
          <tr key={`${d.ts}-${d.symbol}-${i}`}>
            <td className="muted">{new Date(d.ts).toLocaleTimeString()}</td>
            <td>{d.symbol}</td>
            <td><span className={`badge ${d.action}`}>{d.action}</span></td>
            <td>${d.price.toFixed(2)}</td>
            <td>{d.executed
              ? <span className="exec-yes">✓ done</span>
              : <span className="exec-no">skipped</span>}</td>
            <td className="muted" title={d.reason}>
              {short(d.reason)}{d.count > 1 && <span className="dup-count"> ×{d.count}</span>}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
