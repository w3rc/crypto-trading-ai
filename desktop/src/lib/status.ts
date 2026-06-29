import type { Status, Decision } from "./parse";

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

export type ModeTone = "live" | "live-unarmed" | "shadow" | "paper" | "halted";

export function modeBadge(mode?: string, halted?: boolean, armed?: boolean): { label: string; tone: ModeTone } {
  if (halted) return { label: "HALTED", tone: "halted" };
  if (mode === "live") return armed ? { label: "LIVE", tone: "live" } : { label: "LIVE · UNARMED", tone: "live-unarmed" };
  if (mode === "shadow") return { label: "SHADOW", tone: "shadow" };
  return { label: "PAPER", tone: "paper" };
}

function fmtAge(sec: number): string {
  if (sec < 60) return `${Math.round(sec)}s`;
  if (sec < 3600) return `${Math.round(sec / 60)}m`;
  return `${Math.round(sec / 3600)}h`;
}

export function freshness(status: Status | null, nowMs: number): { ageSec: number | null; label: string; stale: boolean } {
  if (!status?.ts) return { ageSec: null, label: "no data · is the bot running?", stale: true };
  const ageSec = Math.max(0, (nowMs - Date.parse(status.ts)) / 1000);
  const interval = status.interval_seconds ?? 900;
  return { ageSec, label: `updated ${fmtAge(ageSec)} ago`, stale: ageSec > 2.5 * interval };
}

export function brainHealth(decisions: Decision[]): { state: "ok" | "degraded" | "unknown"; count: number } {
  if (!decisions.length) return { state: "unknown", count: 0 };
  if (!decisions[decisions.length - 1].reason.startsWith("llm-fallback:")) return { state: "ok", count: 0 };
  let count = 0;
  for (let i = decisions.length - 1; i >= 0 && decisions[i].reason.startsWith("llm-fallback:"); i--) count++;
  return { state: "degraded", count };
}
