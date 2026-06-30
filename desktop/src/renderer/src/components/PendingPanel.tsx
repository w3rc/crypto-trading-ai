import { useState } from "react";
import type { Pending, Status } from "../../../lib/parse";

const api = (window as unknown as {
  api: {
    executeSuggestion: (s: string) => Promise<{ ok: boolean; stderrTail: string }>;
    dismissSuggestion: (s: string) => Promise<unknown>;
  };
}).api;

function ago(ts: string, now: number): string {
  const ms = now - new Date(ts).getTime();
  if (!isFinite(ms) || ms < 60000) return "just now";
  const m = Math.floor(ms / 60000);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  return h < 24 ? `${h}h ago` : `${Math.floor(h / 24)}d ago`;
}

export default function PendingPanel({ pending, status }: { pending: Pending; status: Status | null }): React.JSX.Element | null {
  const syms = Object.keys(pending);
  const [busy, setBusy] = useState("");
  const [msg, setMsg] = useState<{ sym: string; text: string; err: boolean } | null>(null);
  if (!syms.length) return null;
  const isLive = status?.mode === "live";

  const execute = async (sym: string): Promise<void> => {
    const p = pending[sym];
    if (isLive && !window.confirm(`Place a REAL market ${p.action.toUpperCase()} of ${sym}? This uses real funds.`)) return;
    setBusy(sym); setMsg(null);
    try {
      const r = await api.executeSuggestion(sym);
      setMsg({ sym, text: r.ok ? "Executed — updating…" : (r.stderrTail || "Execute failed"), err: !r.ok });
    } catch (e) {
      setMsg({ sym, text: String(e), err: true });
    } finally {
      setBusy("");
    }
  };

  const dismiss = async (sym: string): Promise<void> => {
    setBusy(sym);
    try { await api.dismissSuggestion(sym); } finally { setBusy(""); }
  };

  return (
    <section className="card pending-panel">
      <h2>Pending suggestions <span className="muted">— approve to trade</span></h2>
      {syms.map((sym) => {
        const p = pending[sym];
        return (
          <div className="pending-row" key={sym}>
            <span className="pending-sym">{sym}</span>
            <span className={`pending-side ${p.action}`}>{p.action.toUpperCase()}</span>
            <span className="pending-reason">{p.reason}</span>
            <span className="muted">{ago(p.ts, Date.now())} · @ ${p.price.toFixed(2)}</span>
            <button className="bt-run" disabled={busy === sym} onClick={() => execute(sym)}>
              {isLive ? "Execute (LIVE)" : "Execute"}
            </button>
            <button className="bt-ghost" disabled={busy === sym} onClick={() => dismiss(sym)}>Dismiss</button>
            {msg && msg.sym === sym && <span className={msg.err ? "bt-error" : "muted"}>{msg.text}</span>}
          </div>
        );
      })}
    </section>
  );
}
