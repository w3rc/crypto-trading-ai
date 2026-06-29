import { test, expect } from "vitest";
import { leverageMode, shortingLabel, fundingSummary, accruedLabel, modeBadge } from "./status";
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
