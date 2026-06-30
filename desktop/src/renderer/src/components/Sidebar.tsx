import { useState, useEffect } from "react";
import type { Status, Decision } from "../../../lib/parse";
import { modeBadge, freshness, brainHealth } from "../../../lib/status";

export type View = "overview" | "positions" | "activity" | "sentiment" | "backtest" | "settings";

const NAV: { id: View; label: string }[] = [
  { id: "overview", label: "Overview" },
  { id: "positions", label: "Positions" },
  { id: "activity", label: "Activity" },
  { id: "sentiment", label: "Sentiment" },
  { id: "backtest", label: "Backtest" },
  { id: "settings", label: "Settings" },
];

const MODES: { id: string; label: string }[] = [
  { id: "paper", label: "Paper" },
  { id: "shadow", label: "Shadow" },
  { id: "live", label: "Live" },
];

const api = (window as unknown as { api: { setMode?: (m: string) => Promise<void> } }).api;

export default function Sidebar({ status, view, onNavigate, decisions }: {
  status: Status | null;
  view: View;
  onNavigate: (v: View) => void;
  decisions: Decision[];
}) {
  const badge = modeBadge(status?.mode, status?.halted, status?.armed);
  const fresh = freshness(status, Date.now());   // re-evaluated on every 5s poll re-render
  const brain = brainHealth(decisions);

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

      <div className={`rail-fresh${fresh.stale ? " stale" : ""}`}>
        {fresh.stale && fresh.ageSec !== null ? `STALE · ${fresh.label}` : fresh.label}
      </div>

      {brain.state !== "unknown" && (
        <div className={`brain-chip brain-${brain.state}`}>
          {brain.state === "ok" ? "Brain OK" : `Brain DEGRADED${brain.count > 1 ? ` · ${brain.count} cycles` : ""}`}
        </div>
      )}

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
      </div>
    </aside>
  );
}
