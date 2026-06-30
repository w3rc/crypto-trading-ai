import { test, expect } from "vitest";
import { parseTradesCsv, parseDecisions, parseSentiment } from "./parse";

test("parseTradesCsv parses header + rows, coerces numbers", () => {
  const csv = "ts,symbol,side,qty,price,fee\nt1,BTC/USDT,buy,0.5,60000,0.3\nt2,BTC/USDT,sell,0.5,61000,0.305\n";
  const trades = parseTradesCsv(csv);
  expect(trades).toHaveLength(2);
  expect(trades[0]).toEqual({ ts: "t1", symbol: "BTC/USDT", side: "buy", qty: 0.5, price: 60000, fee: 0.3 });
  expect(trades[1].side).toBe("sell");
});

test("parseTradesCsv tolerates empty / header-only input", () => {
  expect(parseTradesCsv("")).toEqual([]);
  expect(parseTradesCsv("ts,symbol,side,qty,price,fee\n")).toEqual([]);
});

test("parseDecisions parses jsonl, skips blank lines", () => {
  const jsonl = '{"ts":"t1","symbol":"BTC/USDT","action":"hold","reason":"weak","price":60000,"executed":false}\n\n'
              + '{"ts":"t2","symbol":"ETH/USDT","action":"buy","reason":"dip","price":1600,"executed":true}\n';
  const ds = parseDecisions(jsonl);
  expect(ds).toHaveLength(2);
  expect(ds[1]).toEqual({ ts: "t2", symbol: "ETH/USDT", action: "buy", reason: "dip", price: 1600, executed: true });
});

test("parseDecisions tolerates empty input", () => {
  expect(parseDecisions("")).toEqual([]);
});

test("parseDecisions skips a torn line and keeps the rest", () => {
  const text = [
    JSON.stringify({ ts: "t1", symbol: "BTC/USDT", action: "hold", reason: "x", price: 1, executed: false }),
    '{"ts":"t2","symbol":"ETH',                       // torn / half-written line
    JSON.stringify({ ts: "t3", symbol: "ETH/USDT", action: "buy", reason: "y", price: 2, executed: true }),
  ].join("\n");
  const out = parseDecisions(text);
  expect(out.map((d) => d.ts)).toEqual(["t1", "t3"]);   // bad line skipped, others kept
});

test("parseSentiment round-trips a snapshot", () => {
  const json = JSON.stringify({
    ts: "2026-06-26T00:00:00+00:00", strategy: "sentiment_rule",
    symbols: { "BTC/USDT": { blended: -0.62,
      sources: { fear_greed: -0.78, cryptopanic: null, reddit: null, x_twitter: null } } },
  });
  const s = parseSentiment(json);
  expect(s.strategy).toBe("sentiment_rule");
  expect(s.symbols["BTC/USDT"].blended).toBe(-0.62);
  expect(s.symbols["BTC/USDT"].sources.fear_greed).toBe(-0.78);
  expect(s.symbols["BTC/USDT"].sources.reddit).toBeNull();
});

import { parseBacktestCsv } from "./parse";

test("parseBacktestCsv parses baseline + data rows", () => {
  const csv = "ts,equity,buy_hold\n,10000,10000\n1700000000000,10250,10100\n";
  const pts = parseBacktestCsv(csv);
  expect(pts).toHaveLength(2);
  expect(pts[0]).toEqual({ ts: "", equity: 10000, buyHold: 10000 });   // baseline (empty ts)
  expect(pts[1]).toEqual({ ts: "1700000000000", equity: 10250, buyHold: 10100 });
});

test("parseBacktestCsv empty / header-only -> []", () => {
  expect(parseBacktestCsv("")).toEqual([]);
  expect(parseBacktestCsv("ts,equity,buy_hold\n")).toEqual([]);
});
