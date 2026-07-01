export type PairLink = { label: string; url: string };

// External destinations for a pair like "BTC/USDT" (bot trades USDT pairs on Binance).
export function pairLinks(symbol: string): PairLink[] {
  const [base, quote] = symbol.split("/");
  return [
    { label: "TradingView", url: `https://www.tradingview.com/chart/?symbol=BINANCE:${base}${quote}` },
    { label: "Hyperliquid", url: `https://app.hyperliquid.xyz/trade/${base}` },
    { label: "DEX Screener", url: `https://dexscreener.com/search?q=${encodeURIComponent(`${base}/${quote}`)}` },
  ];
}
