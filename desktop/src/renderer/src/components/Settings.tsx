import { useEffect, useState } from "react";
import type { Status } from "../../../lib/parse";

type Schedule = { enabled: boolean; intervalSeconds: number };
type Result = { ok: boolean; stderrTail: string } | null;

const api = (window as unknown as {
  api: {
    runBot: () => Promise<{ ok: boolean; code: number | null; stderrTail: string }>;
    getSchedule: () => Promise<Schedule>;
    setSchedule: (s: Schedule) => Promise<Schedule>;
    setAutoExecute: (on: boolean) => Promise<void>;
  };
}).api;

export default function Settings({ status }: { status: Status | null }): React.JSX.Element {
  const [enabled, setEnabled] = useState(false);
  const [intervalSeconds, setIntervalSeconds] = useState(900);
  const [saved, setSaved] = useState<Schedule | null>(null);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<Result>(null);
  const [saveMsg, setSaveMsg] = useState("");

  const [autoExec, setAutoExec] = useState(false);
  const [autoSeeded, setAutoSeeded] = useState(false);

  useEffect(() => {
    api.getSchedule().then((s) => { setEnabled(s.enabled); setIntervalSeconds(s.intervalSeconds); setSaved(s); });
  }, []);

  useEffect(() => {
    if (!autoSeeded && status && typeof status.auto_execute === "boolean") {
      setAutoExec(status.auto_execute); setAutoSeeded(true);
    }
  }, [status, autoSeeded]);

  const toggleAuto = async (on: boolean): Promise<void> => {
    setAutoExec(on);
    try { await api.setAutoExecute(on); } catch { /* status poll reconciles on failure */ }
  };

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

  return (
    <div className="settings-form">
      <label className="settings-row">
        <input type="checkbox" checked={autoExec} onChange={(e) => toggleAuto(e.target.checked)} />
        Auto-execute trades — when off, the bot only proposes; you Execute/Dismiss each suggestion. In live mode an Execute places a real order.
      </label>
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
