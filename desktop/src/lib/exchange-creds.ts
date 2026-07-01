export type ExchangeId = "hyperliquid" | "binance";

export interface ExchangeCreds {
  activeExchange: ExchangeId;
  testnet: boolean;
  binance: { apiKey: string; secret: string };
  hyperliquid: { walletAddress: string; privateKey: string };
}

// Renderer-safe: booleans only, never secret values.
export interface ExchangeConfigView {
  activeExchange: ExchangeId;
  testnet: boolean;
  binance: { apiKey: boolean; secret: boolean };
  hyperliquid: { walletAddress: boolean; privateKey: boolean };
}

// Partial update from the UI. A blank ("") or absent secret keeps the stored value.
export interface ExchangeConfigUpdate {
  activeExchange?: ExchangeId;
  testnet?: boolean;
  binance?: { apiKey?: string; secret?: string };
  hyperliquid?: { walletAddress?: string; privateKey?: string };
}

export const DEFAULT_CREDS: ExchangeCreds = {
  activeExchange: "hyperliquid",
  testnet: true,
  binance: { apiKey: "", secret: "" },
  hyperliquid: { walletAddress: "", privateKey: "" },
};

export function redact(c: ExchangeCreds): ExchangeConfigView {
  return {
    activeExchange: c.activeExchange,
    testnet: c.testnet,
    binance: { apiKey: !!c.binance.apiKey, secret: !!c.binance.secret },
    hyperliquid: { walletAddress: !!c.hyperliquid.walletAddress, privateKey: !!c.hyperliquid.privateKey },
  };
}

// A field is replaced only when the update carries a non-empty string; otherwise the stored value stays.
function keep(current: string, incoming?: string): string {
  return incoming && incoming.length > 0 ? incoming : current;
}

export function mergeUpdate(current: ExchangeCreds, update: ExchangeConfigUpdate): ExchangeCreds {
  return {
    activeExchange: update.activeExchange ?? current.activeExchange,
    testnet: update.testnet ?? current.testnet,
    binance: {
      apiKey: keep(current.binance.apiKey, update.binance?.apiKey),
      secret: keep(current.binance.secret, update.binance?.secret),
    },
    hyperliquid: {
      walletAddress: keep(current.hyperliquid.walletAddress, update.hyperliquid?.walletAddress),
      privateKey: keep(current.hyperliquid.privateKey, update.hyperliquid?.privateKey),
    },
  };
}

// Env vars for the active exchange only. Empty values are omitted so a blank store
// doesn't shadow a value the operator set in .env. EXCHANGE_TESTNET is always present.
export function envForActive(c: ExchangeCreds): Record<string, string> {
  const env: Record<string, string> = { EXCHANGE_TESTNET: c.testnet ? "1" : "0" };
  const put = (k: string, v: string): void => { if (v) env[k] = v; };
  if (c.activeExchange === "hyperliquid") {
    put("HYPERLIQUID_WALLET_ADDRESS", c.hyperliquid.walletAddress);
    put("HYPERLIQUID_PRIVATE_KEY", c.hyperliquid.privateKey);
  } else {
    put("EXCHANGE_API_KEY", c.binance.apiKey);
    put("EXCHANGE_API_SECRET", c.binance.secret);
  }
  return env;
}
