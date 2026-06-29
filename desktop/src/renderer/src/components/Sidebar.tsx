import type { State, Status } from "../../../lib/parse";
import { modeBadge } from "../../../lib/status";

export type View = "overview" | "positions" | "activity" | "sentiment" | "backtest";

const NAV: { id: View; label: string }[] = [
  { id: "overview", label: "Overview" },
  { id: "positions", label: "Positions" },
  { id: "activity", label: "Activity" },
  { id: "sentiment", label: "Sentiment" },
  { id: "backtest", label: "Backtest" },
];

export default function Sidebar({ status, state, view, onNavigate }: {
  status: Status | null;
  state: State | null;
  view: View;
  onNavigate: (v: View) => void;
}) {
  const badge = modeBadge(status?.mode, status?.halted);
  const cash = state?.cash ?? 0;
  const eq = state?.equity_history;
  const equity = eq && eq.length ? eq[eq.length - 1].equity : cash;
  const start = eq && eq.length ? eq[0].equity : equity;
  const pnl = equity - start;

  return (
    <aside className="sidebar">
      <div className="brand">Crypto Trading Bot</div>

      <div className={`mode-badge mode-${badge.tone}`}>
        <span className="mode-dot" />
        {badge.label}
      </div>

      <div className="rail-acct">
        <div className="rail-eq">${equity.toFixed(2)}</div>
        <div className="rail-pnl" style={{ color: pnl >= 0 ? "var(--up)" : "var(--down)" }}>
          {pnl >= 0 ? "+" : ""}${pnl.toFixed(2)}
        </div>
      </div>

      <nav className="rail-nav">
        {NAV.map((n) => (
          <button
            key={n.id}
            className={`rail-link ${view === n.id ? "active" : ""}`}
            onClick={() => onNavigate(n.id)}
          >
            {n.label}
          </button>
        ))}
      </nav>

      <div className="rail-foot">
        {status ? `${status.exchange} · ${status.strategy}` : "—"}
        <br />
        read-only · polls 5s
      </div>
    </aside>
  );
}
