import { useState, useEffect } from "react";
import type { Status } from "../../../lib/parse";
import { freshness } from "../../../lib/status";
import { STRATEGIES } from "../../../lib/strategies";

export type View = "overview" | "positions" | "pairs" | "activity" | "sentiment" | "backtest" | "settings";

const NAV: { id: View; label: string }[] = [
  { id: "overview", label: "Overview" },
  { id: "positions", label: "Positions" },
  { id: "pairs", label: "Pairs" },
  { id: "activity", label: "Activity" },
  { id: "sentiment", label: "Sentiment" },
  { id: "backtest", label: "Backtest" },
  { id: "settings", label: "Settings" },
];

// Offered modes. Shadow is intentionally not offered — Paper (simulated + P&L) supersedes it,
// and shadow lives on only as the unarmed-live runtime fallback. See modesFor().
const MODES: { id: string; label: string }[] = [
  { id: "paper", label: "Paper" },
  { id: "live", label: "Live" },
];

// If the bot is already in an unlisted mode (e.g. legacy "shadow"), keep it visible as an
// active, de-selectable segment so the user isn't stranded with nothing highlighted; it
// vanishes once they switch to an offered mode (choose() no-ops on the already-active one).
function modesFor(active: string): { id: string; label: string }[] {
  if (MODES.some((m) => m.id === active)) return MODES;
  return [...MODES, { id: active, label: active.charAt(0).toUpperCase() + active.slice(1) }];
}

// 16px line icons (stroke = currentColor, so they inherit the nav link's color/active accent)
const ICONS: Record<View, React.JSX.Element> = {
  overview: (<><rect x="3" y="3" width="7" height="7" rx="1.5" /><rect x="14" y="3" width="7" height="7" rx="1.5" /><rect x="14" y="14" width="7" height="7" rx="1.5" /><rect x="3" y="14" width="7" height="7" rx="1.5" /></>),
  positions: (<><path d="M12 2 2 7l10 5 10-5-10-5z" /><path d="m2 17 10 5 10-5" /><path d="m2 12 10 5 10-5" /></>),
  pairs: (<><path d="m17 2 4 4-4 4" /><path d="M3 11v-1a4 4 0 0 1 4-4h14" /><path d="m7 22-4-4 4-4" /><path d="M21 13v1a4 4 0 0 1-4 4H3" /></>),
  activity: (<path d="M22 12h-4l-3 9L9 3l-3 9H2" />),
  sentiment: (<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />),
  backtest: (<><path d="M3 3v5h5" /><path d="M3.05 13A9 9 0 1 0 6 5.3L3 8" /><path d="M12 7v5l4 2" /></>),
  settings: (<><line x1="4" y1="21" x2="4" y2="14" /><line x1="4" y1="10" x2="4" y2="3" /><line x1="12" y1="21" x2="12" y2="12" /><line x1="12" y1="8" x2="12" y2="3" /><line x1="20" y1="21" x2="20" y2="16" /><line x1="20" y1="12" x2="20" y2="3" /><line x1="2" y1="14" x2="6" y2="14" /><line x1="10" y1="8" x2="14" y2="8" /><line x1="18" y1="16" x2="22" y2="16" /></>),
};

function railIcon(id: View): React.JSX.Element {
  return (
    <svg className="rail-ic" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor"
         strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{ICONS[id]}</svg>
  );
}

const api = (window as unknown as { api: {
  setMode?: (m: string) => Promise<void>;
  setStrategy?: (s: string) => Promise<void>;
} }).api;

export default function Sidebar({ status, view, onNavigate }: {
  status: Status | null;
  view: View;
  onNavigate: (v: View) => void;
}) {
  const fresh = freshness(status, Date.now());   // re-evaluated on every 5s poll re-render

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

  const currentStrat = status?.strategy ?? "hybrid";
  const [pendingStrat, setPendingStrat] = useState<string | null>(null);
  useEffect(() => {
    if (pendingStrat && status?.strategy === pendingStrat) setPendingStrat(null);  // bot caught up
  }, [status?.strategy, pendingStrat]);
  const activeStrat = pendingStrat ?? currentStrat;

  const chooseStrat = (s: string): void => {
    if (s === activeStrat) return;
    setPendingStrat(s);
    void api?.setStrategy?.(s).catch(() => setPendingStrat(null));   // failed write -> drop optimistic
  };

  return (
    <aside className="sidebar">
      <div className="brand">
        <span className="brand-mark" aria-hidden="true">
          <svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor"
               strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M7 3v3" /><rect x="4.5" y="6" width="5" height="8" rx="1.5" /><path d="M7 14v4" />
            <path d="M17 6v3" /><rect x="14.5" y="9" width="5" height="6" rx="1.5" /><path d="M17 15v3" />
          </svg>
        </span>
        <span className="brand-name">Crypto Trading Bot</span>
      </div>

      <div className={`rail-fresh${fresh.stale ? " stale" : ""}`}>
        {fresh.stale && fresh.ageSec !== null ? `Stale · ${fresh.label}` : fresh.label}
      </div>

      <nav className="rail-nav">
        {NAV.map((n) => (
          <button
            key={n.id}
            className={view === n.id ? "rail-link active" : "rail-link"}
            aria-current={view === n.id ? "page" : undefined}
            onClick={() => onNavigate(n.id)}
          >
            {railIcon(n.id)}
            <span>{n.label}</span>
          </button>
        ))}
      </nav>

      <div className="rail-controls">
        <div className="rail-toggle">
          <div className="rail-toggle-label">Mode</div>
          <div className="seg">
            {modesFor(activeMode).map((m) => (
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

        <div className="rail-toggle">
          <div className="rail-toggle-label">Strategy</div>
          <select className="rail-select" value={activeStrat}
                  onChange={(e) => chooseStrat(e.target.value)}>
            {STRATEGIES.map((s) => (
              <option key={s.id} value={s.id}>{s.label}</option>
            ))}
          </select>
          {pendingStrat && pendingStrat !== currentStrat && <div className="rail-toggle-hint">applies next cycle</div>}
        </div>
      </div>
    </aside>
  );
}
