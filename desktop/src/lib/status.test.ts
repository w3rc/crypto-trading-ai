import { test, expect } from "vitest";
import { leverageMode, shortingLabel, fundingSummary, accruedLabel, modeBadge, freshness, brainHealth } from "./status";
import type { Status } from "./parse";

const mk = (over: Partial<Status["risk"]>): Status => ({
  ts: "t", strategy: "hybrid", exchange: "binance",
  risk: { allow_short: false, leverage: 1, maintenance_margin_pct: 0.005,
          funding_rate: 0, funding_interval_hours: 8, max_position_pct: 0.25, stop_loss_pct: 0.05, ...over },
  funding: { accrued: 0, last_funding_ts: null },
});

test("leverageMode", () => {
  expect(leverageMode(1)).toBe("1× (off)");
  expect(leverageMode(5)).toBe("5×");
  expect(leverageMode(undefined)).toBe("1× (off)");
});

test("shortingLabel", () => {
  expect(shortingLabel(true)).toBe("on");
  expect(shortingLabel(false)).toBe("off");
});

test("fundingSummary", () => {
  expect(fundingSummary(null)).toBe("off");
  expect(fundingSummary(mk({ funding_rate: 0 }))).toBe("off");
  expect(fundingSummary(mk({ funding_rate: 0.0001, funding_interval_hours: 8 }))).toBe("0.010%/8h");
});

test("accruedLabel", () => {
  expect(accruedLabel(0)).toBe("$0.00");
  expect(accruedLabel(0.8)).toBe("+$0.80 received");
  expect(accruedLabel(-1.234)).toBe("−$1.23 paid");
});

test("modeBadge maps mode+armed to tone+label", () => {
  expect(modeBadge("paper", false, false)).toEqual({ label: "PAPER", tone: "paper" });
  expect(modeBadge("shadow", false, false)).toEqual({ label: "SHADOW", tone: "shadow" });
  expect(modeBadge("live", false, true)).toEqual({ label: "LIVE", tone: "live" });
  expect(modeBadge("live", false, false)).toEqual({ label: "LIVE · UNARMED", tone: "live-unarmed" });
  expect(modeBadge(undefined, false, false)).toEqual({ label: "PAPER", tone: "paper" });
});

test("modeBadge: halted overrides every mode", () => {
  expect(modeBadge("live", true, true)).toEqual({ label: "HALTED", tone: "halted" });
  expect(modeBadge("paper", true, false)).toEqual({ label: "HALTED", tone: "halted" });
  expect(modeBadge("shadow", true, false)).toEqual({ label: "HALTED", tone: "halted" });
  expect(modeBadge(undefined, true, false)).toEqual({ label: "HALTED", tone: "halted" });
});

test("freshness: fresh status -> ago label, not stale", () => {
  const now = 1_000_000_000_000;
  const status = { ts: new Date(now - 8_000).toISOString(), interval_seconds: 900 } as any;
  const f = freshness(status, now);
  expect(f.stale).toBe(false);
  expect(f.ageSec).toBe(8);
  expect(f.label).toBe("updated 8s ago");
});

test("freshness: past 2.5x interval -> stale", () => {
  const now = 1_000_000_000_000;
  const status = { ts: new Date(now - 2_300_000).toISOString(), interval_seconds: 900 } as any; // 2300s > 2250s
  expect(freshness(status, now).stale).toBe(true);
});

test("freshness: missing interval -> 900s fallback", () => {
  const now = 1_000_000_000_000;
  const fresh = { ts: new Date(now - 2_000_000).toISOString() } as any;  // 2000s < 2250s -> not stale
  const stale = { ts: new Date(now - 2_300_000).toISOString() } as any;  // 2300s > 2250s -> stale
  expect(freshness(fresh, now).stale).toBe(false);
  expect(freshness(stale, now).stale).toBe(true);
});

test("freshness: no status -> no-data, stale", () => {
  const f = freshness(null, 1_000_000_000_000);
  expect(f.ageSec).toBe(null);
  expect(f.stale).toBe(true);
  expect(f.label).toBe("no data · is the bot running?");
});

test("freshness: minute and hour formatting", () => {
  const now = 1_000_000_000_000;
  expect(freshness({ ts: new Date(now - 240_000).toISOString() } as any, now).label).toBe("updated 4m ago");
  expect(freshness({ ts: new Date(now - 7_200_000).toISOString() } as any, now).label).toBe("updated 2h ago");
});

test("brainHealth: latest reason is llm-fallback -> degraded with trailing count", () => {
  const decisions = [
    { reason: "rsi ok" }, { reason: "llm-fallback: x" }, { reason: "llm-fallback: y" },
  ] as any;
  expect(brainHealth(decisions)).toEqual({ state: "degraded", count: 2 });
});

test("brainHealth: latest reason healthy -> ok", () => {
  expect(brainHealth([{ reason: "llm-fallback: x" }, { reason: "buy signal" }] as any))
    .toEqual({ state: "ok", count: 0 });
});

test("brainHealth: no decisions -> unknown", () => {
  expect(brainHealth([])).toEqual({ state: "unknown", count: 0 });
});
