import type { SentimentSnapshot, SourceScores } from "../../../lib/parse";
import { sentimentLabel, gaugePct } from "../../../lib/sentiment";

const SOURCE_ROWS: [keyof SourceScores, string][] = [
  ["fear_greed", "F&G"], ["cryptopanic", "news"], ["reddit", "reddit"], ["x_twitter", "X"],
];

function fmt(v: number | null): string {
  return v === null ? "—" : (v >= 0 ? "+" : "") + v.toFixed(2);
}

function color(score: number): string {
  return score > 0.15 ? "var(--up)" : score < -0.15 ? "var(--down)" : "var(--muted)";
}

export default function SentimentPanel({ sentiment }: { sentiment: SentimentSnapshot | null }) {
  if (!sentiment) return <div className="empty">Sentiment off.</div>;
  const syms = Object.entries(sentiment.symbols);
  if (!syms.length) return <div className="empty">No sentiment yet.</div>;
  return (
    <div>
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
    </div>
  );
}
