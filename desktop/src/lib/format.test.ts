import { test, expect } from "vitest";
import { formatDecisionTime } from "./format";

test("formatDecisionTime shows time only for the same local day", () => {
  const now = new Date("2026-06-30T12:00:00").getTime();   // local noon
  const ts = "2026-06-30T05:00:00";                         // same local day
  expect(formatDecisionTime(ts, now)).toBe(new Date(ts).toLocaleTimeString());
});

test("formatDecisionTime prefixes the date on a different day", () => {
  const now = new Date("2026-06-30T12:00:00").getTime();
  const ts = "2026-06-29T20:00:00";                         // previous local day
  const out = formatDecisionTime(ts, now);
  const timeOnly = new Date(ts).toLocaleTimeString();
  expect(out).toContain(timeOnly);    // time-of-day still present
  expect(out).not.toBe(timeOnly);     // but prefixed with the date (locale-independent check)
});
