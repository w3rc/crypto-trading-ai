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

test("readSnapshot reads sentiment.json, null when absent", async () => {
  const dir = mkdtempSync(join(tmpdir(), "snap-sent-"));
  writeFileSync(join(dir, "sentiment.json"), JSON.stringify({
    ts: "t1", strategy: "sentiment_rule",
    symbols: { "BTC/USDT": { blended: 0.2,
      sources: { fear_greed: 0.2, cryptopanic: null, reddit: null, x_twitter: null } } },
  }));
  const snap = await readSnapshot(dir);
  expect(snap.sentiment?.strategy).toBe("sentiment_rule");
  expect(snap.sentiment?.symbols["BTC/USDT"].blended).toBe(0.2);
  rmSync(dir, { recursive: true, force: true });

  const empty = mkdtempSync(join(tmpdir(), "snap-nosent-"));
  expect((await readSnapshot(empty)).sentiment).toBeNull();   // missing file -> null
  rmSync(empty, { recursive: true, force: true });
});

test("readSnapshot reads status.json + backtest_equity.csv, defaults when absent", async () => {
  const dir = mkdtempSync(join(tmpdir(), "snap-status-"));
  writeFileSync(join(dir, "status.json"), JSON.stringify({
    ts: "t1", strategy: "hybrid", exchange: "binance",
    risk: { allow_short: true, leverage: 5, maintenance_margin_pct: 0.005,
            funding_rate: 0.0001, funding_interval_hours: 8, max_position_pct: 0.25, stop_loss_pct: 0.05 },
    funding: { accrued: -1.5, last_funding_ts: "t0" },
  }));
  writeFileSync(join(dir, "backtest_equity.csv"), "ts,equity,buy_hold\n,10000,10000\n1,10200,10100\n");
  const snap = await readSnapshot(dir);
  expect(snap.status?.risk.leverage).toBe(5);
  expect(snap.status?.funding.accrued).toBe(-1.5);
  expect(snap.backtest).toHaveLength(2);
  rmSync(dir, { recursive: true, force: true });

  const empty = mkdtempSync(join(tmpdir(), "snap-nostatus-"));
  const s = await readSnapshot(empty);
  expect(s.status).toBeNull();      // missing -> null
  expect(s.backtest).toEqual([]);   // missing -> []
  rmSync(empty, { recursive: true, force: true });
});

test("readSnapshot parses pending.json into snap.pending", async () => {
  const d = mkdtempSync(join(tmpdir(), "snap-"));
  writeFileSync(join(d, "pending.json"), JSON.stringify({
    "ETH/USDT": { ts: "t", action: "sell", size: 1, reason: "r", price: 1583.35 },
  }));
  const snap = await readSnapshot(d);
  expect(snap.pending["ETH/USDT"].action).toBe("sell");
});

test("readSnapshot pending defaults to {} when absent", async () => {
  const d = mkdtempSync(join(tmpdir(), "snap-"));
  const snap = await readSnapshot(d);
  expect(snap.pending).toEqual({});
});
