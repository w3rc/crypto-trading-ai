import { useEffect, useState } from "react";
import type { Status, State } from "../../../lib/parse";
import { validSymbol } from "../../../lib/symbols";

type Schedule = { enabled: boolean; intervalSeconds: number };
type Result = { ok: boolean; stderrTail: string } | null;

const api = (window as unknown as {
  api: {
    runBot: () => Promise<{ ok: boolean; code: number | null; stderrTail: string }>;
    getSchedule: () => Promise<Schedule>;
    setSchedule: (s: Schedule) => Promise<Schedule>;
    setSymbols: (list: string[]) => Promise<string[]>;
  };
}).api;

export default function Settings({ status, state }: { status: Status | null; state: State | null }): React.JSX.Element {
  const [enabled, setEnabled] = useState(false);
  const [intervalSeconds, setIntervalSeconds] = useState(900);
  const [saved, setSaved] = useState<Schedule | null>(null);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<Result>(null);
  const [saveMsg, setSaveMsg] = useState("");

  const [symbols, setSymbols] = useState<string[]>([]);
  const [symInput, setSymInput] = useState("");
  const [seeded, setSeeded] = useState(false);
  const [symMsg, setSymMsg] = useState("");

  useEffect(() => {
    api.getSchedule().then((s) => { setEnabled(s.enabled); setIntervalSeconds(s.intervalSeconds); setSaved(s); });
  }, []);

  useEffect(() => {
    if (!seeded && status?.symbols) { setSymbols(status.symbols); setSeeded(true); }
  }, [status, seeded]);

  const save = async (): Promise<void> => {
    try {
      const s = await api.setSchedule({ enabled, intervalSeconds });
      setEnabled(s.enabled); setIntervalSeconds(s.intervalSeconds); setSaved(s); setSaveMsg("");
    } catch (err) {
      setSaveMsg(`Could not save schedule: ${String(err)}`);
    }
  };

  const runNow = async (): Promise<void> => {
    if (running) return;
    setRunning(true);
    setResult(null);
    try {
      const r = await api.runBot();
      setResult({ ok: r.ok, stderrTail: r.stderrTail });
    } catch (err) {
      setResult({ ok: false, stderrTail: String(err) });
    } finally {
      setRunning(false);
    }
  };

  const hasPosition = (sym: string): boolean => (state?.positions?.[sym]?.qty ?? 0) !== 0;

  const addSymbol = (): void => {
    const s = symInput.trim().toUpperCase();
    if (validSymbol(s) && !symbols.includes(s)) { setSymbols([...symbols, s]); setSymInput(""); setSymMsg(""); }
    else if (!validSymbol(s)) setSymMsg(`Not a valid pair: "${symInput}" (use BASE/QUOTE, e.g. SOL/USDT)`);
  };

  const removeSymbol = (s: string): void => {
    if (!hasPosition(s)) setSymbols(symbols.filter((x) => x !== s));
  };

  const saveSymbols = async (): Promise<void> => {
    try {
      setSymbols(await api.setSymbols(symbols));
      setSymMsg("");
    } catch (err) {
      setSymMsg(`Could not save symbols: ${String(err)}`);
    }
  };

  return (
    <div className="settings-form">
      <div className="settings-section-label">Trading pairs</div>
      <div className="symbol-chips">
        {symbols.map((s) => (
          <span className="symbol-chip" key={s}>
            {s}
            <button className="symbol-x" disabled={hasPosition(s)}
                    title={hasPosition(s) ? "close the position first" : "remove"}
                    onClick={() => removeSymbol(s)}>×</button>
          </span>
        ))}
      </div>
      <div className="settings-actions">
        <input className="symbol-input" placeholder="e.g. SOL/USDT" value={symInput}
               onChange={(e) => setSymInput(e.target.value)}
               onKeyDown={(e) => { if (e.key === "Enter") addSymbol(); }} />
        <button className="bt-run" onClick={addSymbol}>Add</button>
        <button className="bt-run" disabled={!symbols.length} onClick={saveSymbols}>Save symbols</button>
      </div>
      <div className="settings-summary">Each pair = one more LLM call per cycle; applies next cycle.</div>
      {symMsg && <div className="bt-result bt-error">{symMsg}</div>}

      <label className="settings-row">
        <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
        Run the bot on a schedule (while this app is open)
      </label>
      <label className="settings-row">
        Interval (seconds)
        <input type="number" min={60} max={86400} value={intervalSeconds}
               onChange={(e) => setIntervalSeconds(Number(e.target.value))} />
      </label>
      <div className="settings-actions">
        <button className="bt-run" onClick={save}>Save schedule</button>
        <button className="bt-run" disabled={running} onClick={runNow}>{running ? "Running…" : "Run now"}</button>
      </div>
      {saved && (
        <div className="settings-summary">
          {saved.enabled ? `Scheduler on — every ${saved.intervalSeconds}s` : "Scheduler off"} · keep the interval near
          {" "}config.interval_seconds for accurate freshness.
        </div>
      )}
      {saveMsg && <div className="bt-result bt-error">{saveMsg}</div>}
      {result && result.ok && <div className="bt-result">Bot cycle complete — dashboard updating…</div>}
      {result && !result.ok && (
        <div className="bt-result bt-error">Bot run failed<pre>{result.stderrTail || "(no output)"}</pre></div>
      )}
    </div>
  );
}
