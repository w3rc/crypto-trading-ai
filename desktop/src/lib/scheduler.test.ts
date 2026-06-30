import { test, expect } from "vitest";
import { clampInterval, parseSchedule } from "./scheduler";

test("clampInterval floors at 60, caps at 86400, and rounds", () => {
  expect(clampInterval(900)).toBe(900);
  expect(clampInterval(30)).toBe(60);        // floor
  expect(clampInterval(120.6)).toBe(121);    // rounds
  expect(clampInterval(1e12)).toBe(86400);   // cap — else intervalSeconds*1000 overflows setInterval into a 1ms tick
});

test("clampInterval falls back to 900 for 0 / NaN / Infinity", () => {
  expect(clampInterval(0)).toBe(900);
  expect(clampInterval(NaN)).toBe(900);
  expect(clampInterval(Infinity)).toBe(900);   // never an interval that won't tick
});

test("parseSchedule coerces valid input", () => {
  expect(parseSchedule({ enabled: true, intervalSeconds: 300 })).toEqual({ enabled: true, intervalSeconds: 300 });
});

test("parseSchedule defaults missing/garbage fields and clamps", () => {
  expect(parseSchedule({})).toEqual({ enabled: false, intervalSeconds: 900 });
  expect(parseSchedule(null)).toEqual({ enabled: false, intervalSeconds: 900 });
  expect(parseSchedule({ enabled: "yes", intervalSeconds: "x" })).toEqual({ enabled: false, intervalSeconds: 900 });
  expect(parseSchedule({ enabled: true, intervalSeconds: 10 })).toEqual({ enabled: true, intervalSeconds: 60 });
});
