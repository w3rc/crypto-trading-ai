# Exchange Credentials — Slice 4: Settings "Exchange" UI (Implementation Plan)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the operator connect an exchange from the dashboard — pick the exchange, enter credentials (masked, never re-displayed), toggle testnet, save, and test the connection — all over the Slice-1 IPCs, with the agent-wallet-only guidance inline.

**Architecture:** A focused `ExchangeSettings.tsx` component (rendered as a new section by `Settings.tsx`) reads the redacted config via `window.api.getExchangeConfig()`, shows credential fields that adapt to the selected exchange, and saves partial updates via `window.api.setExchangeConfig()` (blank field = keep stored, per Slice 1's `mergeUpdate`). A "Test connection" button runs a new read-only engine entry point through a new IPC.

**Tech Stack:** React/TypeScript, Electron IPC, vitest + a Playwright CLI smoke, Python (test-connection entry). Builds on Slice 1 (`get-exchange-config` / `set-exchange-config` IPCs + redacted view) and Slice 2 (`make_exchange` + `fetch_balance`).

Spec: `docs/superpowers/specs/2026-07-01-exchange-connection-hyperliquid-design.md`.

## Global Constraints

- The renderer never receives or displays a stored secret — fields show **set / not set**, inputs are masked (`type="password"`), and a blank field on save keeps the stored value.
- The credential fields adapt to the selected exchange: Hyperliquid → **Wallet address** + **Private key**; Binance → **API key** + **API secret**.
- The Hyperliquid selection shows the inline safety note: use an **agent wallet** (trade-only, no withdrawals).
- Save sends only `{ activeExchange, testnet, <exchange>: { …non-empty fields } }` — never empty strings for untouched secrets.
- Hyperliquid is the default selection when the stored `activeExchange` is hyperliquid (Slice 2 default).
- "Test connection" is **read-only** (a balance fetch) — it never places an order.

## File Structure

- Create `desktop/src/renderer/src/components/ExchangeSettings.tsx` — the Exchange section (one responsibility: view/edit exchange credentials).
- Modify `desktop/src/renderer/src/components/Settings.tsx` — render `<ExchangeSettings />` as a section.
- Modify `desktop/src/renderer/src/index.css` — a few classes for the masked field + note.
- Create `engine/test_connection.py` — read-only balance check entry point.
- Modify `desktop/src/main/engine.ts`, `desktop/src/main/index.ts`, `desktop/src/preload/index.ts` — the `test-exchange-connection` IPC.

---

### Task 1: ExchangeSettings component (view / edit / save)

**Files:**
- Create: `desktop/src/renderer/src/components/ExchangeSettings.tsx`
- Modify: `desktop/src/renderer/src/components/Settings.tsx` (add the import + render the section)
- Modify: `desktop/src/renderer/src/index.css`
- Test: a Playwright CLI smoke (see Step 5)

**Interfaces:**
- Consumes (Slice 1): `window.api.getExchangeConfig(): Promise<ExchangeConfigView>` and `window.api.setExchangeConfig(update): Promise<ExchangeConfigView>` where
  `ExchangeConfigView = { activeExchange: "hyperliquid"|"binance"; testnet: boolean; binance: {apiKey: boolean; secret: boolean}; hyperliquid: {walletAddress: boolean; privateKey: boolean} }`.
- Produces: default-exported `ExchangeSettings` React component.

- [ ] **Step 1: Write the component**

Create `desktop/src/renderer/src/components/ExchangeSettings.tsx`:

```tsx
import { useEffect, useState } from "react";

type ExchangeId = "hyperliquid" | "binance";
type ExchangeConfigView = {
  activeExchange: ExchangeId;
  testnet: boolean;
  binance: { apiKey: boolean; secret: boolean };
  hyperliquid: { walletAddress: boolean; privateKey: boolean };
};

const api = (window as unknown as { api: {
  getExchangeConfig: () => Promise<ExchangeConfigView>;
  setExchangeConfig: (u: unknown) => Promise<ExchangeConfigView>;
} }).api;

const FIELDS: Record<ExchangeId, { key: string; label: string }[]> = {
  hyperliquid: [
    { key: "walletAddress", label: "Wallet address" },
    { key: "privateKey", label: "Private key (agent wallet)" },
  ],
  binance: [
    { key: "apiKey", label: "API key" },
    { key: "secret", label: "API secret" },
  ],
};

export default function ExchangeSettings(): React.JSX.Element {
  const [view, setView] = useState<ExchangeConfigView | null>(null);
  const [exchange, setExchange] = useState<ExchangeId>("hyperliquid");
  const [testnet, setTestnet] = useState(true);
  const [inputs, setInputs] = useState<Record<string, string>>({});
  const [msg, setMsg] = useState("");

  useEffect(() => {
    api.getExchangeConfig().then((v) => {
      setView(v); setExchange(v.activeExchange); setTestnet(v.testnet);
    });
  }, []);

  const isSet = (key: string): boolean =>
    !!(view && (view[exchange] as Record<string, boolean>)[key]);

  const save = async (): Promise<void> => {
    const creds: Record<string, string> = {};
    for (const f of FIELDS[exchange]) {
      const val = inputs[f.key];
      if (val && val.length > 0) creds[f.key] = val;   // blank keeps the stored value
    }
    try {
      const v = await api.setExchangeConfig({ activeExchange: exchange, testnet, [exchange]: creds });
      setView(v); setInputs({}); setMsg("Saved.");
    } catch (err) {
      setMsg(`Could not save: ${String(err)}`);
    }
  };

  return (
    <section className="settings-group">
      <div className="settings-group-title">Exchange</div>

      <label className="field-row">
        <span className="field-label">Exchange</span>
        <select className="rail-select" value={exchange}
                onChange={(e) => { setExchange(e.target.value as ExchangeId); setInputs({}); setMsg(""); }}>
          <option value="hyperliquid">Hyperliquid</option>
          <option value="binance">Binance</option>
        </select>
      </label>

      {FIELDS[exchange].map((f) => (
        <label className="field-row" key={f.key}>
          <span className="field-label">{f.label}</span>
          <input type="password" className="cred-input" autoComplete="off"
                 placeholder={isSet(f.key) ? "•••••••• saved" : "not set"}
                 value={inputs[f.key] ?? ""}
                 onChange={(e) => setInputs((s) => ({ ...s, [f.key]: e.target.value }))} />
        </label>
      ))}

      {exchange === "hyperliquid" && (
        <div className="settings-summary cred-note">
          Use a Hyperliquid <b>agent wallet</b> private key — it can trade but not withdraw. Never paste your main wallet key.
        </div>
      )}

      <label className="switch-row" style={{ marginTop: 10 }}>
        <span className="switch">
          <input type="checkbox" checked={testnet} onChange={(e) => setTestnet(e.target.checked)} />
          <span className="switch-slider" />
        </span>
        <span className="switch-label">
          <span className="switch-name">Testnet</span>
          <span className="switch-help">Route shadow/live to the exchange testnet. Turn off for mainnet (real funds).</span>
        </span>
      </label>

      <div className="settings-actions">
        <button className="bt-run" onClick={save}>Save exchange</button>
      </div>
      <div className="settings-summary">Credentials are encrypted on this device and never leave it in plain text. Leave a field blank to keep the saved value.</div>
      {msg && <div className="bt-result">{msg}</div>}
    </section>
  );
}
```

- [ ] **Step 2: Render it in Settings.tsx**

In `desktop/src/renderer/src/components/Settings.tsx`, add the import at the top:

```tsx
import ExchangeSettings from "./ExchangeSettings";
```

And render it as the first section inside the `<div className="settings">` (before the Execution group):

```tsx
    <div className="settings">
      <ExchangeSettings />
```

- [ ] **Step 3: Add CSS**

In `desktop/src/renderer/src/index.css`, add:

```css
.cred-input { font-family: ui-monospace, monospace; letter-spacing: 1px; }
.cred-note { border-left: 2px solid var(--accent); padding-left: 10px; }
```

- [ ] **Step 4: Build**

Run: `cd desktop && npm run build`
Expected: build succeeds, no TS errors.

- [ ] **Step 5: Playwright smoke — the Exchange section**

Create `/tmp/verify-exchange-ui.cjs` (serve `desktop/out/renderer`, stub `window.api` incl. `getExchangeConfig`/`setExchangeConfig`, navigate to Settings, assert):

```js
const pw = require("/home/silverion/projects/myhermes-ai/node_modules/playwright/index.js");
(async () => {
  const b = await pw.chromium.launch();
  const page = await b.newPage({ viewport: { width: 1000, height: 800 } });
  await page.addInitScript(() => {
    const status = { ts: new Date().toISOString(), strategy: "hybrid", exchange: "hyperliquid", mode: "paper", halted: false, armed: false, auto_execute: false, symbols: ["BTC/USDC"], risk: { allow_short: false, leverage: 1, maintenance_margin_pct: 0.005, funding_rate: 0, funding_interval_hours: 8, max_position_pct: 0.25, stop_loss_pct: 0.05 }, funding: { accrued: 0, last_funding_ts: null } };
    window.__saved = null;
    window.api = {
      getSnapshot: async () => ({ state: null, trades: [], decisions: [], sentiment: null, status, backtest: [], pending: {}, backtestHistory: [] }),
      getExchangeConfig: async () => ({ activeExchange: "hyperliquid", testnet: true, binance: { apiKey: false, secret: false }, hyperliquid: { walletAddress: true, privateKey: false } }),
      setExchangeConfig: async (u) => { window.__saved = u; return { activeExchange: u.activeExchange, testnet: u.testnet, binance: { apiKey: false, secret: false }, hyperliquid: { walletAddress: true, privateKey: true } }; },
      getSchedule: async () => ({ enabled: false, intervalSeconds: 900 }), setSchedule: async (s) => s, setAutoExecute: async () => {}, runBot: async () => ({ ok: true, code: 0, stderrTail: "" }), setMode: async () => {}, setStrategy: async () => {}, setSymbols: async (l) => l, openExternal: async () => {}, runSentiment: async () => ({ ok: true }),
    };
  });
  await page.goto("http://127.0.0.1:8151/index.html");
  await page.click("button.rail-link:has-text('Settings')");
  await page.waitForSelector(".settings-group-title:has-text('Exchange')");
  // hyperliquid fields + agent-wallet note visible
  const hlLabels = await page.locator(".field-label").allTextContents();
  const noteVisible = await page.locator(".cred-note").isVisible();
  // wallet field shows "saved", privateKey shows "not set"
  const walletPh = await page.locator(".field-row:has(.field-label:has-text('Wallet address')) .cred-input").getAttribute("placeholder");
  const pkPh = await page.locator(".field-row:has(.field-label:has-text('Private key')) .cred-input").getAttribute("placeholder");
  // switch to Binance -> fields swap, note hidden
  await page.selectOption(".rail-select", "binance");
  const bnLabels = await page.locator(".field-label").allTextContents();
  const noteAfter = await page.locator(".cred-note").count();
  // fill a key and save -> setExchangeConfig called with only non-empty creds
  await page.fill(".field-row:has(.field-label:has-text('API key')) .cred-input", "MYKEY");
  await page.click("button.bt-run:has-text('Save exchange')");
  await page.waitForTimeout(80);
  const saved = await page.evaluate(() => window.__saved);
  await page.screenshot({ path: "/tmp/exchange-ui.png" });
  await b.close();
  const ok = hlLabels.includes("Wallet address") && hlLabels.includes("Private key (agent wallet)") &&
    noteVisible && walletPh.includes("saved") && pkPh === "not set" &&
    bnLabels.includes("API key") && bnLabels.includes("API secret") && noteAfter === 0 &&
    saved && saved.activeExchange === "binance" && saved.binance.apiKey === "MYKEY" && !("secret" in (saved.binance || {}));
  console.log(JSON.stringify({ hlLabels, noteVisible, walletPh, pkPh, bnLabels, noteAfter, saved, ok }));
  process.exit(ok ? 0 : 1);
})();
```

Serve + run:
```bash
python3 -m http.server 8151 --bind 127.0.0.1 --directory desktop/out/renderer >/dev/null 2>&1 &
node /tmp/verify-exchange-ui.cjs   # expect {"...","ok":true} exit 0
```
Expected: `ok:true` — hyperliquid fields + note render, placeholders reflect set/not-set, switching to Binance swaps fields + hides the note, and Save sends only the non-empty `apiKey` (no empty `secret`).

- [ ] **Step 6: Commit**

```bash
git add desktop/src/renderer/src/components/ExchangeSettings.tsx desktop/src/renderer/src/components/Settings.tsx desktop/src/renderer/src/index.css
git commit -m "feat(desktop): Settings Exchange section — enter/save encrypted credentials"
```

---

### Task 2: Test-connection (read-only balance check)

**Files:**
- Create: `engine/test_connection.py`
- Test: `tests/test_test_connection.py`
- Modify: `desktop/src/main/engine.ts`, `desktop/src/main/index.ts`, `desktop/src/preload/index.ts`
- Modify: `desktop/src/renderer/src/components/ExchangeSettings.tsx` (add the button + state)

**Interfaces:**
- Consumes: `engine.config.load_config`, `engine.market.make_exchange` + `fetch_balance`.
- Produces: `window.api.testExchangeConnection(): Promise<{ ok: boolean; code: number | null; stderrTail: string }>`; a "Test connection" button in the Exchange section.

- [ ] **Step 1: Write the failing test**

Create `tests/test_test_connection.py`:

```python
from types import SimpleNamespace
from engine import test_connection


def test_reports_ok_when_balance_fetch_succeeds(monkeypatch, capsys):
    cfg = SimpleNamespace(exchange="hyperliquid", symbols=["BTC/USDC"], mode="shadow",
                          exchange_api_key="", exchange_secret="",
                          exchange_wallet="0xabc", exchange_private_key="0xpk", testnet=True)
    monkeypatch.setattr(test_connection, "load_config", lambda: cfg)
    monkeypatch.setattr(test_connection.market, "make_exchange", lambda *a, **k: object())
    monkeypatch.setattr(test_connection.market, "fetch_balance", lambda ex, syms: (100.0, {}))
    assert test_connection.main() == 0
    assert "ok" in capsys.readouterr().out.lower()


def test_reports_failure_when_fetch_raises(monkeypatch, capsys):
    cfg = SimpleNamespace(exchange="hyperliquid", symbols=["BTC/USDC"], mode="shadow",
                          exchange_api_key="", exchange_secret="",
                          exchange_wallet="", exchange_private_key="", testnet=True)
    monkeypatch.setattr(test_connection, "load_config", lambda: cfg)
    monkeypatch.setattr(test_connection.market, "make_exchange", lambda *a, **k: object())
    def boom(ex, syms): raise RuntimeError("401 unauthorized")
    monkeypatch.setattr(test_connection.market, "fetch_balance", boom)
    assert test_connection.main() == 1
    assert "401" in capsys.readouterr().out
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_test_connection.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'engine.test_connection'`.

- [ ] **Step 3: Write the implementation**

Create `engine/test_connection.py`:

```python
"""Read-only exchange connection check: build the exchange from config and fetch the
real balance. Backs the dashboard's Settings "Test connection" button. Places no orders."""
import logging
import sys

from engine import market
from engine.config import load_config


def main() -> int:
    cfg = load_config()
    try:
        ex = market.make_exchange(cfg.exchange, "shadow", cfg.exchange_api_key, cfg.exchange_secret,
                                  wallet=cfg.exchange_wallet, private_key=cfg.exchange_private_key,
                                  testnet=cfg.testnet)
        cash, _ = market.fetch_balance(ex, cfg.symbols)
    except Exception as e:                       # bad key / network / auth -> reported, never raised
        print(f"connection FAILED: {e}")
        return 1
    net = "testnet" if cfg.testnet else "mainnet"
    print(f"connection ok — {cfg.exchange} ({net}); available quote balance: {cash}")
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    from engine.env import load_dotenv
    load_dotenv()
    sys.exit(main())
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_test_connection.py -q && python -m pytest -q`
Expected: the two new tests pass; full suite green.

- [ ] **Step 5: Wire the IPC (main + preload + engine.ts)**

In `desktop/src/main/engine.ts`, add after `runSentiment`:

```ts
export function testConnection(): Promise<RunResult> {
  return spawnEngine(["-m", "engine.test_connection"]);   // read-only balance check; pinned, no arming
}
```

In `desktop/src/main/index.ts`, import `testConnection` from `./engine` (add to the existing import) and register inside `app.whenReady`:

```ts
    ipcMain.handle("test-exchange-connection", () => testConnection());
```

In `desktop/src/preload/index.ts`, add to the `api` object:

```ts
  testExchangeConnection: () => ipcRenderer.invoke("test-exchange-connection"),
```

- [ ] **Step 6: Add the button to ExchangeSettings**

In `desktop/src/renderer/src/components/ExchangeSettings.tsx`, extend the `api` type with `testExchangeConnection: () => Promise<{ ok: boolean; code: number | null; stderrTail: string }>;`, add state `const [testing, setTesting] = useState(false);` and a handler:

```tsx
  const test = async (): Promise<void> => {
    if (testing) return;
    setTesting(true); setMsg("");
    try {
      const r = await api.testExchangeConnection();
      setMsg(r.ok ? "Connection ok." : `Connection failed${r.stderrTail ? `: ${r.stderrTail}` : ""}.`);
    } catch { setMsg("Connection failed."); } finally { setTesting(false); }
  };
```

And add the button next to "Save exchange" in `.settings-actions`:

```tsx
        <button className="bt-run" disabled={testing} onClick={test}>{testing ? "Testing…" : "Test connection"}</button>
```

- [ ] **Step 7: Build + verify the IPC + Playwright**

Run: `cd desktop && npm run build && grep -c "test-exchange-connection" out/main/index.js` (expect `1`).
Then extend `/tmp/verify-exchange-ui.cjs`'s stub with `testExchangeConnection: async () => ({ ok: true, code: 0, stderrTail: "" })`, click the "Test connection" button, and assert the "Connection ok." message appears. Run it → expect `ok:true`.

- [ ] **Step 8: Commit**

```bash
git add engine/test_connection.py tests/test_test_connection.py desktop/src/main/engine.ts desktop/src/main/index.ts desktop/src/preload/index.ts desktop/src/renderer/src/components/ExchangeSettings.tsx
git commit -m "feat: Test-connection — read-only balance check from Settings"
```

---

## Self-Review

**Spec coverage (Slice 4 items):**
- Exchange section: dropdown (HL default), adaptive credential fields (masked), testnet toggle, agent-wallet note, Save → Task 1. ✓
- Set / not-set display, never the secret; blank keeps stored → Task 1 (`isSet` placeholder + `save` filters non-empty). ✓
- Test connection (read-only balance) → Task 2. ✓

**Placeholder scan:** Complete code in every code step; the Playwright scripts are complete. ✓

**Type consistency:** `ExchangeConfigView` shape matches Slice 1's `redact` output exactly; the save payload matches Slice 1's `ExchangeConfigUpdate` (partial, per-exchange); `testExchangeConnection` return type matches the `RunResult` other IPCs use. ✓

**Note (main-process change):** Task 2 adds an IPC (`test-exchange-connection`), so the dev app must be running the built main (electron-vite hot-reloads it since #43; verify with the grep step).

**Out of scope:** dynamic USDC symbol validation for the Pairs tab (the deferred Slice-2 `fetch_balance` quote finding); Slice 3 Task 3 testnet round-trip.
