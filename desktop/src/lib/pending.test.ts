import { test, expect } from "vitest";
import { parsePending, removePending } from "./pending";
import { mkdtempSync, writeFileSync, readFileSync } from "fs";
import { tmpdir } from "os";
import { join } from "path";

test("parsePending keeps valid entries and drops malformed", () => {
  const raw = {
    "BTC/USDT": { ts: "t", action: "buy", size: 0.5, reason: "r", price: 100 },
    "BAD/ONE": { size: 1 },        // no action -> dropped
    "BAD/TWO": "nope",             // not an object -> dropped
  };
  const out = parsePending(raw);
  expect(Object.keys(out)).toEqual(["BTC/USDT"]);
  expect(out["BTC/USDT"].action).toBe("buy");
});

test("parsePending returns {} for non-objects", () => {
  expect(parsePending([1, 2])).toEqual({});
  expect(parsePending(null)).toEqual({});
  expect(parsePending("x")).toEqual({});
});

test("removePending removes one key, preserves others", async () => {
  const d = mkdtempSync(join(tmpdir(), "pend-"));
  writeFileSync(join(d, "pending.json"), JSON.stringify({
    "BTC/USDT": { ts: "t", action: "buy", size: 1, reason: "r", price: 1 },
    "ETH/USDT": { ts: "t", action: "sell", size: 1, reason: "r", price: 2 },
  }));
  const left = await removePending(d, "BTC/USDT");
  expect(Object.keys(left)).toEqual(["ETH/USDT"]);
  expect(Object.keys(JSON.parse(readFileSync(join(d, "pending.json"), "utf8")))).toEqual(["ETH/USDT"]);
});

test("removePending on a missing file is a no-op {}", async () => {
  const d = mkdtempSync(join(tmpdir(), "pend-"));
  expect(await removePending(d, "BTC/USDT")).toEqual({});
});
