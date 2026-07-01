import { useEffect, useState } from "react";
import type { Snapshot, Status } from "../../lib/parse";
import { leverageMode, shortingLabel, fundingSummary } from "../../lib/status";
import EquityChart from "./components/EquityChart";
import PositionsTable from "./components/PositionsTable";
import DecisionLog from "./components/DecisionLog";
import TradesTable from "./components/TradesTable";
import SentimentPanel from "./components/SentimentPanel";
import BacktestChart from "./components/BacktestChart";
import BacktestForm from "./components/BacktestForm";
import Settings from "./components/Settings";
import ErrorBoundary from "./components/ErrorBoundary";
import Sidebar, { type View } from "./components/Sidebar";
import PendingPanel from "./components/PendingPanel";
import SymbolManager from "./components/SymbolManager";

const EMPTY: Snapshot = { state: null, trades: [], decisions: [], sentiment: null, status: null, backtest: [], pending: {} };
const api = (window as unknown as { api: { getSnapshot: () => Promise<Snapshot> } }).api;

export default function App(): React.JSX.Element {
  const [snap, setSnap] = useState<Snapshot>(EMPTY);
  const [view, setView] = useState<View>("overview");

  useEffect(() => {
    let alive = true;
    const load = async (): Promise<void> => {
      try {
        const s = await api.getSnapshot();
        if (alive) setSnap(s);
      } catch {
        /* keep last good snapshot */
      }
    };
    load();
    const id = setInterval(load, 5000);
    return () => { alive = false; clearInterval(id); };
  }, []);

  return (
    <div className="app">
      <Sidebar status={snap.status} view={view} onNavigate={setView} />
      <main className="main">
        <ErrorBoundary key={view}>
          {view === "overview" && <Overview snap={snap} />}
          {view === "positions" && (
            <div className="grid">
              <PendingPanel pending={snap.pending} status={snap.status} />
              <section className={`card${Object.keys(snap.pending).length ? "" : " span-full"}`}>
                <h2>Open positions</h2><PositionsTable state={snap.state} />
              </section>
            </div>
          )}
          {view === "pairs" && (
            <section className="card"><SymbolManager status={snap.status} state={snap.state} /></section>
          )}
          {view === "activity" && <Activity snap={snap} />}
          {view === "sentiment" && (
            <section className="card"><h2>Sentiment</h2><SentimentPanel sentiment={snap.sentiment} /></section>
          )}
          {view === "backtest" && (
            <section className="card"><h2>Backtest</h2><BacktestForm /><BacktestChart points={snap.backtest} /></section>
          )}
          {view === "settings" && (
            <section className="card"><h2>Settings</h2><Settings status={snap.status} /></section>
          )}
        </ErrorBoundary>
      </main>
    </div>
  );
}

function Overview({ snap }: { snap: Snapshot }): React.JSX.Element {
  const cash = snap.state?.cash ?? 0;
  const eq = snap.state?.equity_history;
  const equity = eq && eq.length ? eq[eq.length - 1].equity : cash;
  const start = eq && eq.length ? eq[0].equity : equity;
  const pnl = equity - start;
  return (
    <>
      <div className="kpi-row">
        <section className="card kpi">
          <div className="label">Equity</div>
          <div className="value">${equity.toFixed(2)}</div>
        </section>
        <section className="card kpi">
          <div className="label">Cash</div>
          <div className="value">${cash.toFixed(2)}</div>
        </section>
        <section className="card kpi">
          <div className="label">P&amp;L</div>
          <div className="value" style={{ color: pnl >= 0 ? "var(--up)" : "var(--down)" }}>
            {pnl >= 0 ? "+$" : "−$"}{Math.abs(pnl).toFixed(2)}
          </div>
        </section>
      </div>
      <div className="grid">
        <section className="card span-full"><h2>Equity curve</h2><EquityChart history={eq ?? []} /></section>
        <section className="card"><h2>Open positions</h2><PositionsTable state={snap.state} /></section>
        <section className="card"><h2>Risk</h2><RiskCard status={snap.status} /></section>
      </div>
    </>
  );
}

function RiskCard({ status }: { status: Status | null }): React.JSX.Element {
  if (!status) return <div className="empty">No status yet.</div>;
  const r = status.risk;
  const chips: [string, string][] = [
    ["Leverage", leverageMode(r.leverage)],
    ["Shorting", shortingLabel(r.allow_short)],
    ["Funding", fundingSummary(status)],
    ["Max position", `${(r.max_position_pct * 100).toFixed(0)}%`],
    ["Stop", `${(r.stop_loss_pct * 100).toFixed(0)}%`],
    ["Maint. margin", `${(r.maintenance_margin_pct * 100).toFixed(2)}%`],
  ];
  return (
    <div className="chips">
      {chips.map(([k, v]) => (
        <div className="chip" key={k}><span className="chip-k">{k}</span><span className="chip-v">{v}</span></div>
      ))}
    </div>
  );
}

function Activity({ snap }: { snap: Snapshot }): React.JSX.Element {
  return (
    <div className="grid">
      <section className="card"><h2>Decisions</h2><DecisionLog decisions={snap.decisions} /></section>
      <section className="card"><h2>Trades</h2><TradesTable trades={snap.trades} /></section>
    </div>
  );
}
