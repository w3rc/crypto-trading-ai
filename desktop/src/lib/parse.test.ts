import { test, expect } from "vitest";
import { parseTradesCsv, parseDecisions } from "./parse";

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
