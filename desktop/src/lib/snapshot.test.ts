import { test, expect } from "vitest";
import { mkdtempSync, writeFileSync, rmSync } from "fs";
import { tmpdir } from "os";
import { join } from "path";
import { readSnapshot } from "./snapshot";

test("readSnapshot reads all three files", async () => {
  const dir = mkdtempSync(join(tmpdir(), "snap-"));
  writeFileSync(join(dir, "state.json"), JSON.stringify({
    cash: 8000, positions: { "BTC/USDT": { qty: 0.1, avg_price: 60000, stop_price: 57000 } },
    equity_history: [{ ts: "t1", equity: 10000 }, { ts: "t2", equity: 10100 }],
  }));
  writeFileSync(join(dir, "trades.csv"), "ts,symbol,side,qty,price,fee\nt1,BTC/USDT,buy,0.1,60000,0.06\n");
  writeFileSync(join(dir, "decisions.jsonl"),
    '{"ts":"t1","symbol":"BTC/USDT","action":"buy","reason":"dip","price":60000,"executed":true}\n');
  const snap = await readSnapshot(dir);
  expect(snap.state?.cash).toBe(8000);
  expect(snap.trades).toHaveLength(1);
  expect(snap.decisions[0].action).toBe("buy");
  rmSync(dir, { recursive: true, force: true });
});

test("readSnapshot tolerates a totally empty data dir", async () => {
  const dir = mkdtempSync(join(tmpdir(), "snap-empty-"));
  const snap = await readSnapshot(dir);
  expect(snap.state).toBeNull();
  expect(snap.trades).toEqual([]);
  expect(snap.decisions).toEqual([]);
  rmSync(dir, { recursive: true, force: true });
});
