import { Area, AreaChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { EquityPoint } from "../../../lib/parse";

export default function EquityChart({ history }: { history: EquityPoint[] }) {
  if (!history.length) return <div className="empty">No equity history yet — run the bot.</div>;
  const data = history.map((p, i) => ({ i, equity: p.equity, ts: p.ts }));
  return (
    <div className="chartbox">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 8 }}>
          <defs>
            <linearGradient id="eq" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#7c8bff" stopOpacity={0.5} />
              <stop offset="100%" stopColor="#7c8bff" stopOpacity={0} />
            </linearGradient>
          </defs>
          <XAxis dataKey="i" hide />
          <YAxis stroke="#93a0bd" width={64} domain={["auto", "auto"]} tickFormatter={(v) => `$${Math.round(v)}`} />
          <Tooltip
            contentStyle={{ background: "#131a2e", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 10, color: "#e8edf7" }}
            formatter={(v: number) => [`$${v.toFixed(2)}`, "equity"]}
            labelFormatter={(_, p) => (p && p[0] ? String(p[0].payload.ts) : "")}
          />
          <Area type="monotone" dataKey="equity" stroke="#7c8bff" strokeWidth={2} fill="url(#eq)" />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
