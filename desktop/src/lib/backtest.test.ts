import { test, expect } from "vitest";
import { buildBacktestArgs, isIsoDate } from "./backtest";

test("buildBacktestArgs with since only", () => {
  expect(buildBacktestArgs({ since: "2026-01-01" })).toEqual([
    "-m", "engine.backtest", "--since", "2026-01-01", "--out", "data/backtest_equity.csv",
  ]);
});

test("buildBacktestArgs with since and until", () => {
  expect(buildBacktestArgs({ since: "2026-01-01", until: "2026-03-01" })).toEqual([
    "-m", "engine.backtest",
    "--since", "2026-01-01",
    "--until", "2026-03-01",
    "--out", "data/backtest_equity.csv",
  ]);
});

test("buildBacktestArgs threads --strategy when set", () => {
  expect(buildBacktestArgs({ since: "2026-01-01", until: "2026-03-01", strategy: "ma_cross" })).toEqual([
    "-m", "engine.backtest",
    "--since", "2026-01-01",
    "--until", "2026-03-01",
    "--strategy", "ma_cross",
    "--out", "data/backtest_equity.csv",
  ]);
});

test("isIsoDate validates YYYY-MM-DD", () => {
  expect(isIsoDate("2026-01-01")).toBe(true);
  expect(isIsoDate("2026-1-1")).toBe(false);
  expect(isIsoDate("")).toBe(false);
  expect(isIsoDate("not a date")).toBe(false);
});
