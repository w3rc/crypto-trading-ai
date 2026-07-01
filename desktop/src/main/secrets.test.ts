import { describe, test, expect, vi, beforeEach } from "vitest";
import { join } from "path";

// vi.hoisted() runs before vi.mock() factories, so factories can safely close over h.
const h = vi.hoisted(() => ({
  files: new Map<string, Buffer>(),
  enc: { available: true },
}));

vi.mock("electron", () => ({
  app: { getPath: (_: string) => "/fake-userdata" },
  safeStorage: {
    isEncryptionAvailable: () => h.enc.available,
    // Reversible fake: prepend "ENC:" so we can assert the blob isn't raw JSON.
    encryptString: (s: string) => Buffer.from("ENC:" + s),
    decryptString: (b: Buffer) => b.toString().replace(/^ENC:/, ""),
  },
}));

vi.mock("fs", () => ({
  existsSync: (p: string) => h.files.has(p),
  readFileSync: (p: string) => {
    const v = h.files.get(p);
    if (!v) throw new Error("ENOENT");
    return v;
  },
  writeFileSync: (p: string, b: Buffer) => { h.files.set(p, b); },
}));

import { getExchangeConfig, setExchangeConfig, exchangeEnv } from "./secrets";

const PATH = join("/fake-userdata", "exchange-creds.enc");

beforeEach(() => {
  h.files.clear();
  h.enc.available = true;
});

// ─── no file → defaults ───────────────────────────────────────────────────────
describe("getExchangeConfig — no file", () => {
  test("returns default view when no file exists", () => {
    const view = getExchangeConfig();
    expect(view.activeExchange).toBe("hyperliquid");
    expect(view.testnet).toBe(true);
    expect(view.hyperliquid.privateKey).toBe(false);
    expect(view.hyperliquid.walletAddress).toBe(false);
    expect(view.binance.apiKey).toBe(false);
    expect(view.binance.secret).toBe(false);
  });
});

// ─── keychain unavailable → throw, no write ──────────────────────────────────
describe("setExchangeConfig — encryption unavailable", () => {
  test("throws and writes nothing when keychain unavailable", () => {
    h.enc.available = false;
    expect(() =>
      setExchangeConfig({ hyperliquid: { privateKey: "0xpk" } })
    ).toThrow(/secure storage unavailable/);
    expect(h.files.size).toBe(0);
  });
});

// ─── round-trip + redaction ───────────────────────────────────────────────────
describe("setExchangeConfig — round-trip + redaction", () => {
  test("returned view shows presence flags, not secret values", () => {
    const view = setExchangeConfig({
      hyperliquid: { walletAddress: "0xabc", privateKey: "0xpk" },
    });
    expect(view.hyperliquid).toEqual({ walletAddress: true, privateKey: true });
    // No secret must leak into the JSON-serialisable view.
    expect(JSON.stringify(view)).not.toContain("0xpk");
    expect(JSON.stringify(view)).not.toContain("0xabc");
  });

  test("stored bytes are encrypted (start with ENC:, not raw JSON)", () => {
    setExchangeConfig({ hyperliquid: { walletAddress: "0xabc", privateKey: "0xpk" } });
    const stored = h.files.get(PATH);
    expect(stored).toBeDefined();
    expect(stored!.toString()).toMatch(/^ENC:/);
    // The raw private-key must NOT appear outside the encrypted envelope.
    expect(stored!.toString().slice(4)).toContain("0xpk"); // inside the payload
    expect(stored!.toString().slice(0, 4)).toBe("ENC:"); // envelope present
  });

  test("exchangeEnv reads back the stored creds correctly", () => {
    setExchangeConfig({ hyperliquid: { walletAddress: "0xabc", privateKey: "0xpk" } });
    expect(exchangeEnv()).toEqual({
      HYPERLIQUID_WALLET_ADDRESS: "0xabc",
      HYPERLIQUID_PRIVATE_KEY: "0xpk",
      EXCHANGE_TESTNET: "1",
    });
  });
});

// ─── corrupt blob → defaults, not throw ──────────────────────────────────────
describe("getExchangeConfig — corrupt blob", () => {
  test("returns defaults without throwing when blob is corrupt", () => {
    h.files.set(PATH, Buffer.from("not-encrypted-garbage-{{{"));
    const view = getExchangeConfig();
    expect(view.activeExchange).toBe("hyperliquid");
    expect(view.hyperliquid.privateKey).toBe(false);
  });
});

// ─── file exists but keychain unavailable → defaults ─────────────────────────
describe("getExchangeConfig — file exists but keychain becomes unavailable", () => {
  test("returns defaults when keychain is unavailable at read time", () => {
    // Write valid creds while encryption is available.
    setExchangeConfig({ binance: { apiKey: "bk", secret: "bs" } });
    expect(h.files.has(PATH)).toBe(true);
    // Simulate OS keychain becoming unavailable.
    h.enc.available = false;
    const view = getExchangeConfig();
    expect(view.binance.apiKey).toBe(false);
    expect(view.activeExchange).toBe("hyperliquid");
  });
});
