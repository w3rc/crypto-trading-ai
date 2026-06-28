import type { Status } from "../../../lib/parse";
import { leverageMode, shortingLabel, fundingSummary, accruedLabel } from "../../../lib/status";

export default function StatusStrip({ status }: { status: Status | null }) {
  if (!status) return <div className="empty">Waiting for the bot to write status…</div>;
  const r = status.risk;
  const chips: [string, string][] = [
    ["Mode", (status.mode ?? "paper").toUpperCase()],
    ["Strategy", status.strategy],
    ["Exchange", status.exchange],
    ["Leverage", leverageMode(r.leverage)],
    ["Shorting", shortingLabel(r.allow_short)],
    ["Funding", fundingSummary(status)],
    ["Accrued", accruedLabel(status.funding.accrued)],
    ["Max position", `${(r.max_position_pct * 100).toFixed(0)}%`],
    ["Stop", `${(r.stop_loss_pct * 100).toFixed(0)}%`],
  ];
  return (
    <div className="chips">
      {chips.map(([k, v]) => (
        <div className="chip" key={k}>
          <span className="chip-k">{k}</span><span className="chip-v">{v}</span>
        </div>
      ))}
    </div>
  );
}
