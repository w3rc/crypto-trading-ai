import { useEffect, useState } from "react";
import type { Status } from "../../../lib/parse";
import { STRATEGIES, LLM_STRATEGIES } from "../../../lib/strategies";

type Result = { ok: boolean; stderrTail: string } | null;

const api = (window as unknown as {
  api: { runBacktest: (o: { since: string; until?: string; strategy?: string }) => Promise<{ ok: boolean; code: number | null; stderrTail: string }> };
}).api;

const isoToday = (): string => new Date().toISOString().slice(0, 10);
const isoYearsAgo = (n: number): string => {
  const d = new Date();
  d.setFullYear(d.getFullYear() - n);
  return d.toISOString().slice(0, 10);
};

export default function BacktestForm({ status }: { status: Status | null }): React.JSX.Element {
  const [since, setSince] = useState(isoYearsAgo(5));   // default: last 5 years
  const [until, setUntil] = useState(isoToday());        // default: today
  const [strategy, setStrategy] = useState("indicator_rule");   // safe non-LLM default
  const [seeded, setSeeded] = useState(false);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<Result>(null);

  // seed from the live strategy, but never default to an LLM strategy — a multi-year hybrid backtest is costly
  useEffect(() => {
    if (!seeded && status?.strategy) {
      setStrategy(LLM_STRATEGIES.has(status.strategy) ? "indicator_rule" : status.strategy);
      setSeeded(true);
    }
  }, [status, seeded]);

  const run = async (): Promise<void> => {
    if (!since || running) return;
    setRunning(true);
    setResult(null);
    try {
      const r = await api.runBacktest({ since, until: until || undefined, strategy });
      setResult({ ok: r.ok, stderrTail: r.stderrTail });
    } catch (err) {
      setResult({ ok: false, stderrTail: String(err) });   // IPC rejected — never leave the button stuck on "Running…"
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="bt-form">
      <label>Strategy
        <select value={strategy} onChange={(e) => setStrategy(e.target.value)}>
          {STRATEGIES.map((s) => (<option key={s.id} value={s.id}>{s.label}</option>))}
        </select>
      </label>
      <label>Since<input type="date" value={since} onChange={(e) => setSince(e.target.value)} /></label>
      <label>Until<input type="date" value={until} onChange={(e) => setUntil(e.target.value)} /></label>
      <button className="bt-run" disabled={!since || running} onClick={run}>
        {running ? "Running…" : "Run backtest"}
      </button>
      {LLM_STRATEGIES.has(strategy) && (
        <div className="bt-result bt-error">
          AI (hybrid) runs an LLM call per candle — a multi-year backtest is slow and costly. Use a short range, or pick a rule-based strategy.
        </div>
      )}
      {result && result.ok && <div className="bt-result">Backtest complete — chart updating…</div>}
      {result && !result.ok && (
        <div className="bt-result bt-error">Backtest failed<pre>{result.stderrTail || "(no output)"}</pre></div>
      )}
    </div>
  );
}
