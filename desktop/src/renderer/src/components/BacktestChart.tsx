import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis, Legend } from "recharts";
import type { BacktestPoint } from "../../../lib/parse";

export default function BacktestChart({ points }: { points: BacktestPoint[] }) {
  if (!points.length)
    return <div className="empty">Run a backtest (<code>python -m engine.backtest …</code>) to see results here.</div>;
  const data = points.map((p, i) => ({ i, equity: p.equity, buyHold: p.buyHold }));
  const label = (n: string): string => (n === "equity" ? "strategy" : "buy & hold");
  return (
    <div className="chartbox">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 8 }}>
          <XAxis dataKey="i" hide />
          <YAxis stroke="#93a0bd" width={64} domain={["auto", "auto"]} tickFormatter={(v) => `$${Math.round(v)}`} />
          <Tooltip
            contentStyle={{ background: "#131a2e", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 10, color: "#e8edf7" }}
            formatter={(v: number, n: string) => [`$${v.toFixed(2)}`, label(n)]}
          />
          <Legend formatter={(v: string) => label(v)} />
          <Line type="monotone" dataKey="equity" stroke="#7c8bff" strokeWidth={2} dot={false} />
          <Line type="monotone" dataKey="buyHold" stroke="#93a0bd" strokeWidth={2} strokeDasharray="4 3" dot={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
