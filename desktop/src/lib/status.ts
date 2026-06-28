import type { Status } from "./parse";

export function leverageMode(lev?: number): string {
  return lev && lev > 1 ? `${lev}×` : "1× (off)";
}

export function shortingLabel(allow?: boolean): string {
  return allow ? "on" : "off";
}

export function fundingSummary(status: Status | null): string {
  const r = status?.risk;
  if (!r || r.funding_rate === 0) return "off";
  return `${(r.funding_rate * 100).toFixed(3)}%/${r.funding_interval_hours}h`;
}

export function accruedLabel(accrued?: number): string {
  const a = accrued ?? 0;
  if (a > 0) return `+$${a.toFixed(2)} received`;
  if (a < 0) return `−$${Math.abs(a).toFixed(2)} paid`;
  return "$0.00";
}
