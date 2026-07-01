import { test, expect } from "vitest";
import { pairLinks } from "./links";

test("pairLinks builds the three destinations for BTC/USDT", () => {
  const links = pairLinks("BTC/USDT");
  expect(links).toHaveLength(3);
  expect(links).toEqual([
    { label: "TradingView", url: "https://www.tradingview.com/chart/?symbol=BINANCE:BTCUSDT" },
    { label: "Hyperliquid", url: "https://app.hyperliquid.xyz/trade/BTC" },
    { label: "CoinGecko", url: "https://www.coingecko.com/en/coins/bitcoin" },
  ]);
});

test("pairLinks maps a memecoin base to its verified CoinGecko slug", () => {
  const links = pairLinks("WIF/USDT");
  expect(links[0].url).toBe("https://www.tradingview.com/chart/?symbol=BINANCE:WIFUSDT");
  expect(links[1].url).toBe("https://app.hyperliquid.xyz/trade/WIF");
  expect(links[2]).toEqual({ label: "CoinGecko", url: "https://www.coingecko.com/en/coins/dogwifcoin" });
});

test("pairLinks falls back to CoinGecko search for an untracked base", () => {
  const links = pairLinks("FOO/USDT");
  expect(links[2]).toEqual({ label: "CoinGecko", url: "https://www.coingecko.com/en/search?query=FOO" });
});
