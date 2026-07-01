export type PairLink = { label: string; url: string };

// Verified CoinGecko slugs for the bot's tracked bases (base ticker != slug, e.g. BTC -> bitcoin).
// Resolved from CoinGecko's own search API; anything not here falls back to a CoinGecko search.
const CG_SLUGS: Record<string, string> = {
  BTC: "bitcoin", ETH: "ethereum", SOL: "solana", BNB: "binancecoin", XRP: "ripple",
  ADA: "cardano", DOGE: "dogecoin", AVAX: "avalanche-2", DOT: "polkadot", LINK: "chainlink",
  TRX: "tron", LTC: "litecoin", BCH: "bitcoin-cash", UNI: "uniswap", ATOM: "cosmos",
  XLM: "stellar", NEAR: "near", APT: "aptos", OP: "optimism", FIL: "filecoin",
  INJ: "injective-protocol", SUI: "sui", POL: "polygon-ecosystem-token", SHIB: "shiba-inu",
  PEPE: "pepe", WIF: "dogwifcoin", RENDER: "render-token", TIA: "celestia",
};

function coinGeckoUrl(base: string): string {
  const slug = CG_SLUGS[base];
  return slug
    ? `https://www.coingecko.com/en/coins/${slug}`                              // direct coin page
    : `https://www.coingecko.com/en/search?query=${encodeURIComponent(base)}`;  // fallback for untracked bases
}

// External destinations for a pair like "BTC/USDT" (bot trades USDT pairs on Binance).
export function pairLinks(symbol: string): PairLink[] {
  const [base, quote] = symbol.split("/");
  return [
    { label: "TradingView", url: `https://www.tradingview.com/chart/?symbol=BINANCE:${base}${quote}` },
    { label: "Hyperliquid", url: `https://app.hyperliquid.xyz/trade/${base}` },
    { label: "CoinGecko", url: coinGeckoUrl(base) },
  ];
}
