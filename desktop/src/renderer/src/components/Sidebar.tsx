import { useState, useEffect } from "react";
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

const MODES: { id: string; label: string }[] = [
  { id: "paper", label: "Paper" },
  { id: "shadow", label: "Shadow" },
  { id: "live", label: "Live" },
];

const api = (window as unknown as { api: { setMode?: (m: string) => Promise<void> } }).api;

export default function Sidebar({ status, state, view, onNavigate }: {
  status: Status | null;
  state: State | null;
  view: View;
  onNavigate: (v: View) => void;
}) {
  const badge = modeBadge(status?.mode, status?.halted, status?.armed);
  const cash = state?.cash ?? 0;
  const eq = state?.equity_history;
  const equity = eq && eq.length ? eq[eq.length - 1].equity : cash;
  const start = eq && eq.length ? eq[0].equity : equity;
  const pnl = equity - start;

  const current = status?.mode ?? "paper";
  const [pending, setPending] = useState<string | null>(null);
  useEffect(() => {
    if (pending && status?.mode === pending) setPending(null);   // bot caught up -> clear hint
  }, [status?.mode, pending]);
  const activeMode = pending ?? current;

  const choose = (m: string): void => {
    if (m === activeMode) return;
    if (m === "live" &&
        !window.confirm("Switch bot to LIVE mode? Real orders are placed only if LIVE_TRADING_ARMED=yes is set in the bot's env.")) {
      return;
    }
    setPending(m);
    void api?.setMode?.(m).catch(() => setPending(null));        // failed write -> drop optimistic state
  };

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
          {pnl >= 0 ? "+$" : "−$"}{Math.abs(pnl).toFixed(2)}
        </div>
      </div>

      <nav className="rail-nav">
        {NAV.map((n) => (
          <button
            key={n.id}
            className={view === n.id ? "rail-link active" : "rail-link"}
            aria-current={view === n.id ? "page" : undefined}
            onClick={() => onNavigate(n.id)}
          >
            {n.label}
          </button>
        ))}
      </nav>

      <div className="rail-toggle">
        <div className="rail-toggle-label">Mode</div>
        <div className="seg">
          {MODES.map((m) => (
            <button
              key={m.id}
              className={`seg-btn ${activeMode === m.id ? "active" : ""}`}
              onClick={() => choose(m.id)}
            >
              {m.label}
            </button>
          ))}
        </div>
        {pending && pending !== current && <div className="rail-toggle-hint">applies next cycle</div>}
      </div>

      <div className="rail-foot">
        {status ? `${status.exchange} · ${status.strategy}` : "—"}
        <br />
        polls 5s
      </div>
    </aside>
  );
}
