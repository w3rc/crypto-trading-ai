import { test, expect } from "vitest";
import { validSymbol, parseSymbols } from "./symbols";

test("validSymbol accepts BASE/QUOTE uppercase, rejects the rest", () => {
  expect(validSymbol("BTC/USDT")).toBe(true);
  expect(validSymbol("SOL/USDT")).toBe(true);
  expect(validSymbol("btc/usdt")).toBe(false);
  expect(validSymbol("BTC-USDT")).toBe(false);
  expect(validSymbol("BTCUSDT")).toBe(false);
  expect(validSymbol("")).toBe(false);
});

test("parseSymbols uppercases, filters invalid, dedupes, drops non-strings", () => {
  expect(parseSymbols([" btc/usdt ", "ETH/USDT", "BTC/USDT", "bad", 5, "ETH/USDT"]))
    .toEqual(["BTC/USDT", "ETH/USDT"]);
  expect(parseSymbols("nope")).toEqual([]);
  expect(parseSymbols(null)).toEqual([]);
});
