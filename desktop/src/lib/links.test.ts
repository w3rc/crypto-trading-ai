import { test, expect } from "vitest";
import { pairLinks } from "./links";

test("pairLinks builds the three destinations for BTC/USDT", () => {
  const links = pairLinks("BTC/USDT");
  expect(links).toHaveLength(3);
  expect(links).toEqual([
    { label: "TradingView", url: "https://www.tradingview.com/chart/?symbol=BINANCE:BTCUSDT" },
    { label: "Hyperliquid", url: "https://app.hyperliquid.xyz/trade/BTC" },
    { label: "DEX Screener", url: "https://dexscreener.com/search?q=BTC%2FUSDT" },
  ]);
});

test("pairLinks handles a memecoin pair", () => {
  const links = pairLinks("PEPE/USDT");
  expect(links).toHaveLength(3);
  expect(links[0].url).toBe("https://www.tradingview.com/chart/?symbol=BINANCE:PEPEUSDT");
  expect(links[1].url).toBe("https://app.hyperliquid.xyz/trade/PEPE");
});
