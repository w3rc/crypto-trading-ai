import { describe, test, expect } from "vitest";
import {
  DEFAULT_CREDS, redact, mergeUpdate, envForActive, ExchangeCreds,
} from "./exchange-creds";

const filled: ExchangeCreds = {
  activeExchange: "hyperliquid",
  testnet: true,
  binance: { apiKey: "bk", secret: "bs" },
  hyperliquid: { walletAddress: "0xabc", privateKey: "0xpk" },
};

describe("DEFAULT_CREDS", () => {
  test("defaults to hyperliquid on testnet with empty creds", () => {
    expect(DEFAULT_CREDS.activeExchange).toBe("hyperliquid");
    expect(DEFAULT_CREDS.testnet).toBe(true);
    expect(DEFAULT_CREDS.binance).toEqual({ apiKey: "", secret: "" });
    expect(DEFAULT_CREDS.hyperliquid).toEqual({ walletAddress: "", privateKey: "" });
  });
});

describe("redact", () => {
  test("reports set/not-set booleans, never values", () => {
    const view = redact({ ...filled, binance: { apiKey: "bk", secret: "" } });
    expect(view).toEqual({
      activeExchange: "hyperliquid",
      testnet: true,
      binance: { apiKey: true, secret: false },
      hyperliquid: { walletAddress: true, privateKey: true },
    });
    expect(JSON.stringify(view)).not.toContain("0xpk");
  });
});

describe("mergeUpdate", () => {
  test("a blank/absent secret keeps the stored value", () => {
    const out = mergeUpdate(filled, { hyperliquid: { privateKey: "" } });
    expect(out.hyperliquid.privateKey).toBe("0xpk");       // blank -> unchanged
    expect(out.hyperliquid.walletAddress).toBe("0xabc");   // absent -> unchanged
  });

  test("a non-empty secret replaces the stored value", () => {
    const out = mergeUpdate(filled, { binance: { apiKey: "new" } });
    expect(out.binance.apiKey).toBe("new");
    expect(out.binance.secret).toBe("bs");                 // untouched
  });

  test("updates activeExchange and testnet when provided", () => {
    const out = mergeUpdate(filled, { activeExchange: "binance", testnet: false });
    expect(out.activeExchange).toBe("binance");
    expect(out.testnet).toBe(false);
  });

  test("does not mutate the input", () => {
    const before = JSON.stringify(filled);
    mergeUpdate(filled, { binance: { apiKey: "x" } });
    expect(JSON.stringify(filled)).toBe(before);
  });
});

describe("envForActive", () => {
  test("hyperliquid active -> wallet env vars + testnet flag", () => {
    expect(envForActive(filled)).toEqual({
      HYPERLIQUID_WALLET_ADDRESS: "0xabc",
      HYPERLIQUID_PRIVATE_KEY: "0xpk",
      EXCHANGE_TESTNET: "1",
    });
  });

  test("binance active -> api key/secret + testnet flag off", () => {
    expect(envForActive({ ...filled, activeExchange: "binance", testnet: false })).toEqual({
      EXCHANGE_API_KEY: "bk",
      EXCHANGE_API_SECRET: "bs",
      EXCHANGE_TESTNET: "0",
    });
  });

  test("omits empty credential vars so .env is not clobbered", () => {
    const empty = { ...DEFAULT_CREDS };   // hyperliquid active, empty creds
    expect(envForActive(empty)).toEqual({ EXCHANGE_TESTNET: "1" });
  });
});
