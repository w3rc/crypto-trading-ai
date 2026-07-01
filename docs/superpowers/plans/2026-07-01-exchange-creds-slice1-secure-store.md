# Exchange Credentials — Slice 1: Secure Credential Store (Implementation Plan)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Store exchange credentials OS-encrypted (Electron `safeStorage`), expose a redacted read + a merge-write over IPC, and inject the active exchange's credentials into every engine spawn — with no plaintext on disk and no secret ever returned to the renderer.

**Architecture:** Pure, fully-unit-tested credential logic (shape, redaction, merge, env-mapping) lives in `desktop/src/lib/exchange-creds.ts`. A thin Electron wrapper `desktop/src/main/secrets.ts` uses `safeStorage` to persist an encrypted blob under `userData` and calls the pure logic. `main/index.ts` registers two IPCs; `preload` exposes them; `main/engine.ts` injects the active exchange's env vars at spawn time.

**Tech Stack:** Electron `safeStorage`, TypeScript, vitest. Spec: `docs/superpowers/specs/2026-07-01-exchange-connection-hyperliquid-design.md`.

## Global Constraints

- Secrets are **never** returned to the renderer — the read IPC returns booleans (set / not-set) only.
- Credentials at rest live in `app.getPath("userData")/exchange-creds.enc`, **outside the repo** — never written under the project dir or committed.
- If `safeStorage.isEncryptionAvailable()` is false, **saving throws** with a clear message — never fall back to plaintext.
- Env injection must **not clobber** `.env`: only inject a credential var whose stored value is non-empty. Always inject `EXCHANGE_TESTNET`.
- Default store: `activeExchange: "hyperliquid"`, `testnet: true`, empty credentials.
- Injected env var names: Binance → `EXCHANGE_API_KEY` / `EXCHANGE_API_SECRET`; Hyperliquid → `HYPERLIQUID_WALLET_ADDRESS` / `HYPERLIQUID_PRIVATE_KEY`; plus `EXCHANGE_TESTNET` (`"1"`/`"0"`).
- This slice injects the active exchange's env into the child but changes no engine behavior (Slice 2 consumes it); `LIVE_TRADING_ARMED` pinning is unchanged.

---

### Task 1: Pure credential logic

**Files:**
- Create: `desktop/src/lib/exchange-creds.ts`
- Test: `desktop/src/lib/exchange-creds.test.ts`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `type ExchangeId = "hyperliquid" | "binance"`
  - `interface ExchangeCreds { activeExchange: ExchangeId; testnet: boolean; binance: { apiKey: string; secret: string }; hyperliquid: { walletAddress: string; privateKey: string } }`
  - `interface ExchangeConfigView { activeExchange: ExchangeId; testnet: boolean; binance: { apiKey: boolean; secret: boolean }; hyperliquid: { walletAddress: boolean; privateKey: boolean } }`
  - `interface ExchangeConfigUpdate { activeExchange?: ExchangeId; testnet?: boolean; binance?: { apiKey?: string; secret?: string }; hyperliquid?: { walletAddress?: string; privateKey?: string } }`
  - `const DEFAULT_CREDS: ExchangeCreds`
  - `redact(c: ExchangeCreds): ExchangeConfigView`
  - `mergeUpdate(current: ExchangeCreds, update: ExchangeConfigUpdate): ExchangeCreds`
  - `envForActive(c: ExchangeCreds): Record<string, string>`

- [ ] **Step 1: Write the failing test**

Create `desktop/src/lib/exchange-creds.test.ts`:

```ts
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd desktop && npx vitest run src/lib/exchange-creds.test.ts`
Expected: FAIL — `Failed to resolve import "./exchange-creds"` / functions not defined.

- [ ] **Step 3: Write the implementation**

Create `desktop/src/lib/exchange-creds.ts`:

```ts
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd desktop && npx vitest run src/lib/exchange-creds.test.ts`
Expected: PASS (all cases).

- [ ] **Step 5: Commit**

```bash
git add desktop/src/lib/exchange-creds.ts desktop/src/lib/exchange-creds.test.ts
git commit -m "feat(desktop): pure exchange-credential logic (shape, redact, merge, env-map)"
```

---

### Task 2: safeStorage-backed store

**Files:**
- Create: `desktop/src/main/secrets.ts`

**Interfaces:**
- Consumes (Task 1): `DEFAULT_CREDS`, `redact`, `mergeUpdate`, `envForActive`, `ExchangeConfigView`, `ExchangeConfigUpdate`, `ExchangeCreds`.
- Produces:
  - `getExchangeConfig(): ExchangeConfigView` — decrypt + redact (DEFAULT_CREDS view if absent/undecryptable).
  - `setExchangeConfig(update: ExchangeConfigUpdate): ExchangeConfigView` — load, merge, encrypt, write; returns the new redacted view. Throws `Error("secure storage unavailable")` when `safeStorage.isEncryptionAvailable()` is false.
  - `exchangeEnv(): Record<string, string>` — `envForActive(load())` for spawn injection.

**Note on testability:** `safeStorage` requires the Electron runtime, so this file is verified by the build (typecheck) and by Task 3's integration; the branching logic it depends on is already unit-tested in Task 1. Keep this file thin — no logic beyond load/merge/encrypt/write.

- [ ] **Step 1: Write the implementation**

Create `desktop/src/main/secrets.ts`:

```ts
import { app, safeStorage } from "electron";
import { existsSync, readFileSync, writeFileSync } from "fs";
import { join } from "path";
import {
  DEFAULT_CREDS, redact, mergeUpdate, envForActive,
  ExchangeCreds, ExchangeConfigView, ExchangeConfigUpdate,
} from "../lib/exchange-creds";

function credsPath(): string {
  return join(app.getPath("userData"), "exchange-creds.enc");
}

// Decrypt the stored blob, or fall back to defaults (missing file, unavailable keychain,
// or a corrupt/undecryptable blob) — reads must never throw.
function load(): ExchangeCreds {
  try {
    const p = credsPath();
    if (!existsSync(p) || !safeStorage.isEncryptionAvailable()) return DEFAULT_CREDS;
    const json = safeStorage.decryptString(readFileSync(p));
    return { ...DEFAULT_CREDS, ...JSON.parse(json) } as ExchangeCreds;
  } catch {
    return DEFAULT_CREDS;
  }
}

export function getExchangeConfig(): ExchangeConfigView {
  return redact(load());
}

export function setExchangeConfig(update: ExchangeConfigUpdate): ExchangeConfigView {
  if (!safeStorage.isEncryptionAvailable()) {
    throw new Error("secure storage unavailable — your OS keychain isn't accessible, so keys can't be stored safely");
  }
  const next = mergeUpdate(load(), update);
  writeFileSync(credsPath(), safeStorage.encryptString(JSON.stringify(next)));
  return redact(next);
}

export function exchangeEnv(): Record<string, string> {
  return envForActive(load());
}
```

- [ ] **Step 2: Verify it typechecks**

Run: `cd desktop && npm run build`
Expected: build succeeds (no TS errors); `secrets.ts` compiles into `out/main`.

- [ ] **Step 3: Commit**

```bash
git add desktop/src/main/secrets.ts
git commit -m "feat(desktop): safeStorage-backed exchange credential store"
```

---

### Task 3: IPC + preload + spawn injection

**Files:**
- Modify: `desktop/src/main/index.ts` (imports near line 4–11; `app.whenReady` handler block near line 47–66)
- Modify: `desktop/src/preload/index.ts` (the `api` object, near line 3–19)
- Modify: `desktop/src/main/engine.ts` (`runEngine`, near line 16–25)
- Test: `desktop/src/lib/exchange-creds.test.ts` (already covers the injected env shape — no new unit test; verified via build + Playwright smoke)

**Interfaces:**
- Consumes (Task 2): `getExchangeConfig`, `setExchangeConfig`, `exchangeEnv`.
- Produces: IPC channels `get-exchange-config` / `set-exchange-config`; preload `window.api.getExchangeConfig()` / `window.api.setExchangeConfig(update)`.

- [ ] **Step 1: Inject exchange env into every engine spawn**

In `desktop/src/main/engine.ts`, add to the imports at the top:

```ts
import { exchangeEnv } from "./secrets";
```

Then in `runEngine`, merge the active exchange's env into the child env. Change the `spawn` line from:

```ts
    const child = spawn(pythonPath(repoRoot), args, { cwd: repoRoot, env });
```

to:

```ts
    // Active-exchange credentials layer UNDER the caller's env, so pinnedEnv's
    // LIVE_TRADING_ARMED="no" (and any explicit override) still wins.
    const child = spawn(pythonPath(repoRoot), args, { cwd: repoRoot, env: { ...exchangeEnv(), ...env } });
```

- [ ] **Step 2: Register the IPCs**

In `desktop/src/main/index.ts`, add to the imports (after the `./engine` import near line 6):

```ts
import { getExchangeConfig, setExchangeConfig } from "./secrets";
```

Inside the `app.whenReady().then(() => { ... })` handler block (alongside the other `ipcMain.handle` calls, e.g. after the `set-symbols` handler), add:

```ts
    ipcMain.handle("get-exchange-config", () => getExchangeConfig());
    ipcMain.handle("set-exchange-config", (_e, update) => setExchangeConfig(update));
```

- [ ] **Step 3: Expose them in preload**

In `desktop/src/preload/index.ts`, add to the `api` object (after `openExternal`):

```ts
  getExchangeConfig: () => ipcRenderer.invoke("get-exchange-config"),
  setExchangeConfig: (update: unknown) => ipcRenderer.invoke("set-exchange-config", update),
```

- [ ] **Step 4: Build and confirm the IPCs are present**

Run: `cd desktop && npm run build && grep -c "set-exchange-config" out/main/index.js`
Expected: build succeeds; grep prints `1` (the handler is in the built main).

- [ ] **Step 5: Playwright smoke — preload binding shape**

Create `/tmp/verify-exchange-ipc.cjs` (serve `desktop/out/renderer`, stub `window.api` with the two new methods, and assert the renderer can call them). Minimal check — the real UI is Slice 4:

```js
const pw = require("/home/silverion/projects/myhermes-ai/node_modules/playwright/index.js");
(async () => {
  const b = await pw.chromium.launch();
  const page = await b.newPage();
  await page.addInitScript(() => {
    window.api = { getSnapshot: async () => ({ state: null, trades: [], decisions: [], sentiment: null, status: null, backtest: [], pending: {}, backtestHistory: [] }),
      getExchangeConfig: async () => ({ activeExchange: "hyperliquid", testnet: true, binance: { apiKey: false, secret: false }, hyperliquid: { walletAddress: false, privateKey: false } }),
      setExchangeConfig: async (u) => { window.__saved = u; return { activeExchange: "hyperliquid", testnet: true, binance: { apiKey: false, secret: false }, hyperliquid: { walletAddress: false, privateKey: false } }; } };
  });
  await page.goto("http://127.0.0.1:8150/index.html");
  const view = await page.evaluate(() => window.api.getExchangeConfig());
  const ok = view.activeExchange === "hyperliquid" && view.hyperliquid.privateKey === false;
  await b.close();
  console.log(JSON.stringify({ view, ok }));
  process.exit(ok ? 0 : 1);
})();
```

Run: serve `desktop/out/renderer` on 8150, then `node /tmp/verify-exchange-ipc.cjs`.
Expected: `{"view":{...},"ok":true}` and exit 0.

- [ ] **Step 6: Commit**

```bash
git add desktop/src/main/index.ts desktop/src/preload/index.ts desktop/src/main/engine.ts
git commit -m "feat(desktop): wire exchange-config IPCs + inject active-exchange env at spawn"
```

---

## Self-Review

**Spec coverage (Slice 1 items):**
- OS-encrypted at rest → Task 2 (`safeStorage.encryptString`, `userData/exchange-creds.enc`). ✓
- Blob shape `{ activeExchange, testnet, binance, hyperliquid }` → Task 1 `ExchangeCreds`. ✓
- `get-exchange-config` (non-secret) / `set-exchange-config` → Task 3 IPCs + Task 1 `redact`. ✓
- Spawn-time env injection, active exchange only → Task 3 (`engine.ts`) + Task 1 `envForActive`. ✓
- Keychain-unavailable blocks saving → Task 2 `setExchangeConfig` throws. ✓
- Secrets never returned to renderer → Task 1 `redact` (booleans) + test asserting no value leaks. ✓
- Don't clobber `.env` (omit empty vars) → Task 1 `envForActive` + test; layered UNDER caller env in Task 3. ✓
- Default hyperliquid/testnet/empty → Task 1 `DEFAULT_CREDS` + test. ✓

**Placeholder scan:** No TBD/TODO; every code step carries complete code. ✓

**Type consistency:** `ExchangeCreds` / `ExchangeConfigView` / `ExchangeConfigUpdate` / `envForActive` / `mergeUpdate` / `redact` used identically across Tasks 1–3. Env var names match the Global Constraints verbatim. ✓

**Out of scope for Slice 1:** engine consumption of these env vars (Slice 2), the Settings UI (Slice 4), Hyperliquid order placement (Slice 3).
