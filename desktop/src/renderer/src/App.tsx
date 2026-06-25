import { useEffect, useState } from "react";
import type { Snapshot } from "../../lib/parse";
import EquityChart from "./components/EquityChart";
import PositionsTable from "./components/PositionsTable";
import DecisionLog from "./components/DecisionLog";

const EMPTY: Snapshot = { state: null, trades: [], decisions: [] };
const api = (window as unknown as { api: { getSnapshot: () => Promise<Snapshot> } }).api;

export default function App(): React.JSX.Element {
  const [snap, setSnap] = useState<Snapshot>(EMPTY);

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

  const cash = snap.state?.cash ?? 0;
  const eq = snap.state?.equity_history;
  const equity = eq && eq.length ? eq[eq.length - 1].equity : cash;
  const start = eq && eq.length ? eq[0].equity : 10000; // baseline = first recorded equity
  const pnl = equity - start;

  return (
    <main className="wrap">
      <div className="title">Crypto Paper-Trading Bot</div>
      <div className="sub">Read-only · polls every 5s · {snap.trades.length} trades logged</div>

      <div className="grid">
        <div className="card span2">
          <h2>Account</h2>
          <div className="kpis">
            <div className="kpi"><div className="label">Equity</div><div className="value">${equity.toFixed(2)}</div></div>
            <div className="kpi"><div className="label">Cash</div><div className="value">${cash.toFixed(2)}</div></div>
            <div className="kpi"><div className="label">P&amp;L</div>
              <div className="value" style={{ color: pnl >= 0 ? "var(--up)" : "var(--down)" }}>
                {pnl >= 0 ? "+" : ""}${pnl.toFixed(2)}
              </div>
            </div>
          </div>
        </div>

        <div className="card span2">
          <h2>Equity curve</h2>
          <EquityChart history={eq ?? []} />
        </div>

        <div className="card">
          <h2>Open positions</h2>
          <PositionsTable state={snap.state} />
        </div>

        <div className="card">
          <h2>Decisions <span className="muted" style={{ textTransform: "none", letterSpacing: 0 }}>(* = not executed)</span></h2>
          <DecisionLog decisions={snap.decisions} />
        </div>
      </div>
    </main>
  );
}
