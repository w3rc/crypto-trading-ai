import type { BacktestRun } from "../../../lib/parse";

const LABEL: Record<string, string> = {
  hybrid: "AI (hybrid)", indicator_rule: "Indicator rule", sentiment_rule: "Sentiment rule",
  ma_cross: "MA cross", macd_cross: "MACD cross", rsi_reversion: "RSI reversion", bollinger: "Bollinger",
};

const pct = (x: number): string => `${x >= 0 ? "+" : ""}${(x * 100).toFixed(1)}%`;

function ago(iso: string): string {
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

export default function BacktestHistory({ runs, selectedId, onSelect }: {
  runs: BacktestRun[]; selectedId?: string; onSelect: (r: BacktestRun) => void;
}): React.JSX.Element {
  if (!runs.length) return <div className="empty">No backtests yet — run one above to start comparing.</div>;
  const rows = [...runs].reverse();                              // most recent first
  const best = Math.max(...runs.map((r) => r.total_return));     // most profitable run
  return (
    <table className="bt-history">
      <thead>
        <tr>
          <th>Ran</th><th>Symbols</th><th>Strategy</th><th>Range</th>
          <th className="num">Return</th><th className="num">vs Hold</th>
          <th className="num">Trades</th><th className="num">Max DD</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r, i) => (
          <tr key={r.id ?? i} className={r.id && r.id === selectedId ? "selected" : ""}
              onClick={() => onSelect(r)}>
            <td className="muted">{ago(r.ts)}</td>
            <td>{r.symbols.join(", ")}</td>
            <td>{LABEL[r.strategy] ?? r.strategy}</td>
            <td className="muted">{r.since} → {r.until ?? "now"} · {r.timeframe}</td>
            <td className="num" style={{ color: r.total_return >= 0 ? "var(--up)" : "var(--down)" }}>
              {r.total_return === best && <span className="best-star" title="best return">★ </span>}{pct(r.total_return)}
            </td>
            <td className="num" style={{ color: r.beats_hold ? "var(--up)" : "var(--down)" }}>{pct(r.total_return - r.buy_hold_return)}</td>
            <td className="num">{r.n_trades}</td>
            <td className="num muted">{pct(r.max_drawdown)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
