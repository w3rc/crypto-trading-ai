import { useState } from "react";

type Result = { ok: boolean; stderrTail: string } | null;

const api = (window as unknown as {
  api: { runBacktest: (o: { since: string; until?: string }) => Promise<{ ok: boolean; code: number | null; stderrTail: string }> };
}).api;

export default function BacktestForm(): React.JSX.Element {
  const [since, setSince] = useState("");
  const [until, setUntil] = useState("");
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<Result>(null);

  const run = async (): Promise<void> => {
    if (!since || running) return;
    setRunning(true);
    setResult(null);
    const r = await api.runBacktest({ since, until: until || undefined });
    setRunning(false);
    setResult({ ok: r.ok, stderrTail: r.stderrTail });
  };

  return (
    <div className="bt-form">
      <label>Since<input type="date" value={since} onChange={(e) => setSince(e.target.value)} /></label>
      <label>Until<input type="date" value={until} onChange={(e) => setUntil(e.target.value)} /></label>
      <button className="bt-run" disabled={!since || running} onClick={run}>
        {running ? "Running…" : "Run backtest"}
      </button>
      {result && result.ok && <div className="bt-result">Backtest complete — chart updating…</div>}
      {result && !result.ok && (
        <div className="bt-result bt-error">Backtest failed<pre>{result.stderrTail || "(no output)"}</pre></div>
      )}
    </div>
  );
}
