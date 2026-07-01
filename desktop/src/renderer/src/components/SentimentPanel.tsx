import { useState } from "react";
import type { SentimentSnapshot, SourceScores } from "../../../lib/parse";
import { sentimentLabel, gaugePct } from "../../../lib/sentiment";

const SOURCE_ROWS: [keyof SourceScores, string][] = [
  ["fear_greed", "F&G"], ["cryptopanic", "news"], ["reddit", "reddit"], ["x_twitter", "X"],
];

const api = (window as unknown as {
  api: { runSentiment: () => Promise<{ ok: boolean; code: number | null; stderrTail: string }> };
}).api;

function fmt(v: number | null | undefined): string {
  return v == null ? "—" : (v >= 0 ? "+" : "") + v.toFixed(2);
}

function color(score: number): string {
  return score > 0.15 ? "var(--up)" : score < -0.15 ? "var(--down)" : "var(--muted)";
}

function ago(iso: string): string {
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

export default function SentimentPanel({ sentiment }: { sentiment: SentimentSnapshot | null }) {
  const [running, setRunning] = useState(false);
  const [msg, setMsg] = useState("");

  const analyze = async (): Promise<void> => {
    if (running) return;
    setRunning(true); setMsg("");
    try {
      const r = await api.runSentiment();
      if (!r.ok) setMsg(`Analysis failed${r.stderrTail ? `: ${r.stderrTail}` : ""}.`);
    } catch {
      setMsg("Analysis failed.");
    } finally {
      setRunning(false);
    }
  };

  const syms = Object.entries(sentiment?.symbols ?? {});
  return (
    <div>
      <div className="sent-header">
        <button className="bt-run" disabled={running} onClick={analyze}>{running ? "Analyzing…" : "Analyze now"}</button>
        {sentiment && <span className="muted">updated {ago(sentiment.ts)}</span>}
      </div>
      {msg && <div className="bt-result bt-error">{msg}</div>}
      {!sentiment ? (
        <div className="empty">No sentiment yet — click Analyze now.</div>
      ) : !syms.length ? (
        <div className="empty">No sentiment for the tracked pairs yet.</div>
      ) : (
        <>
          {syms.map(([sym, s]) => (
            <div className="sent-row" key={sym}>
              <div className="sent-head">
                <span>{sym}</span>
                <span style={{ color: color(s.blended) }}>{fmt(s.blended)} · {sentimentLabel(s.blended)}</span>
              </div>
              <div className="gauge"><div className="gauge-marker" style={{ left: `${gaugePct(s.blended)}%` }} /></div>
              <div className="sent-sources">
                {SOURCE_ROWS.map(([k, label]) => (
                  <span className="sent-src" key={k}>{label} <b>{fmt(s.sources[k])}</b></span>
                ))}
              </div>
            </div>
          ))}
          <div className="muted sent-strategy">strategy: {sentiment.strategy}</div>
        </>
      )}
    </div>
  );
}
